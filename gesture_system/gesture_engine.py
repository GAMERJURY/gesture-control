import time, math, os, urllib.request, cv2, mediapipe as mp, pyautogui
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from state import GestureState
from window_control import WindowController
from hud_overlay import HUDOverlay

W,T4,I8,I5,M12,M9,R16,P20 = 0,4,8,5,12,9,16,20

CONN=[(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(0,9),(9,10),(10,11),(11,12),
      (0,13),(13,14),(14,15),(15,16),(0,17),(17,18),(18,19),(19,20),(5,9),(9,13),(13,17)]

SNAP_ZONES={
    "left-half":(.0,.0,.5,1.),"right-half":(.5,.0,1.,1.),
    "top-left":(.0,.0,.5,.5),"top-right":(.5,.0,1.,.5),
    "bottom-left":(.0,.5,.5,1.),"bottom-right":(.5,.5,1.,1.),
    "full":(.0,.0,1.,1.),
}

MODEL_PATH=os.path.join(os.path.dirname(__file__),"hand_landmarker.task")
MODEL_URL="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

def _model():
    if not os.path.exists(MODEL_PATH):
        print("Downloading model (~8MB)...")
        urllib.request.urlretrieve(MODEL_URL,MODEL_PATH)

def _d(a,b): return math.hypot(a.x-b.x,a.y-b.y)

def _draw(frame,lms,col=(0,220,120)):
    h,w=frame.shape[:2]
    pts=[(int(l.x*w),int(l.y*h)) for l in lms]
    for a,b in CONN: cv2.line(frame,pts[a],pts[b],col,2,cv2.LINE_AA)
    for p in pts: cv2.circle(frame,p,4,col,-1)

class EMA:
    def __init__(self,a=.38): self.a,self.x,self.y=a,None,None
    def __call__(self,x,y):
        if self.x is None: self.x,self.y=x,y
        else: self.x=self.a*x+(1-self.a)*self.x; self.y=self.a*y+(1-self.a)*self.y
        return self.x,self.y
    def reset(self): self.x=self.y=None

def _fingers_up(lms):
    tips=[I8,M12,R16,P20]; mcps=[5,9,13,17]
    index_up = lms[I8].y < lms[I5].y
    others = [lms[tips[i]].y < lms[mcps[i]].y for i in range(1,4)]
    thumb_up = lms[T4].x < lms[2].x
    count = sum([index_up]+others)
    if thumb_up and count==0: return 1
    if not thumb_up:
        if count==1 and index_up: return 1
        if count==2 and index_up and others[0]: return 2
        if count==3 and index_up and others[0] and others[1]: return 3
        if count==4: return 4
    if thumb_up and count==4: return 5
    return 0

class GestureEngine:
    def __init__(self,config,state:GestureState,wc:WindowController,hud:HUDOverlay):
        self.cfg,self.s,self.wc=config,state,wc
        self._stop=False; _model()
        opts=mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=mp_vision.RunningMode.VIDEO,num_hands=2,
            min_hand_detection_confidence=.72,min_tracking_confidence=.62)
        self._lm=mp_vision.HandLandmarker.create_from_options(opts)
        self._sm=EMA(); self._ts=0
        self._rps=self._lps=None
        self._sw_cd=self._L_cd=self._num_cd=0
        self._r_pin=False; self._grab_id=self._grab_rect=None
        self._mode="normal"
        self._task_wins=[]; self._prev_px=None
        self._num_confirm=0; self._num_last=0

    def stop(self): self._stop=True

    def run(self):
        c=self.cfg["camera"]
        cap=cv2.VideoCapture(c["index"])
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT,c["height"])
        cap.set(cv2.CAP_PROP_FPS,c["fps"])
        dbg=self.cfg.get("show_debug_window",True)
        while not self._stop and self.s.running:
            ret,frame=cap.read()
            if not ret: time.sleep(.01); continue
            frame=cv2.flip(frame,1); self._ts+=33
            res=self._lm.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)),self._ts)
            hands=self._parse(res)
            self._run(hands,frame.shape)
            if dbg:
                self._dbg(frame,res)
                cv2.imshow("Gesture  (Q hide)",frame)
                if cv2.waitKey(1)&0xFF==ord("q"): dbg=False; cv2.destroyAllWindows()
        cap.release(); cv2.destroyAllWindows(); self._lm.close()

    def _parse(self,res):
        out={}
        if not res.hand_landmarks: return out
        for lms,h in zip(res.hand_landmarks,res.handedness):
            out["Right" if h[0].category_name=="Left" else "Left"]=lms
        return out

    def _run(self,hands,shape):
        s=self.s
        for attr in ("_sw_cd","_L_cd","_num_cd"):
            v=getattr(self,attr)
            if v>0: setattr(self,attr,v-1)

        r=hands.get("Right"); l=hands.get("Left")

        if s.paused:
            s.hud_message="PAUSED  fist=resume"
            for lms in hands.values():
                if self._fist(lms): s.paused=False; s.hud_message="Resumed"
            return

        for lms in hands.values():
            if self._fist(lms): s.paused=True; s.hud_message="PAUSED"; self._reset(); return

        if self._mode=="task":
            self._task_mode(r,shape); return

        if r and self._L_cd==0 and self._is_L(r):
            self._enter_task(); return

        if r: self._drag(r,shape)
        if l: self._vol(l)
        if r and not self._r_pin: self._swipe(r)
        if not r and not l: s.hud_message="No hand"
        elif not self._r_pin: s.hud_message="Ready  |  L = Task View"

    def _drag(self,lms,shape):
        s=self.s; pin=self._pd(lms)<self.cfg["gesture"]["pinch_threshold"]
        if pin:
            if self._rps is None: self._rps=time.time()
            held=(time.time()-self._rps)*1000
            tip=lms[I8]; sx,sy=self._sm(tip.x,tip.y); pos=(sx,sy)
            if not self._r_pin and held>=self.cfg["gesture"]["pinch_hold_ms"]:
                self._r_pin=True; s.r_pinching=True; s.r_pinch_pos=pos
                wid,rect=self.wc.grab_active_window()
                self._grab_id=wid; self._grab_rect=rect; s.grabbed_window_rect=rect
                s.hud_message="Grabbed"
            elif self._r_pin and s.r_pinch_pos:
                dx=int((pos[0]-s.r_pinch_pos[0])*shape[1]*3.2)
                dy=int((pos[1]-s.r_pinch_pos[1])*shape[0]*3.2)
                s.r_pinch_pos=pos; snap=self._snap(pos)
                s.hud_snap_zone=snap; s.hud_message=f"-> {snap}" if snap else "Dragging"
                self.wc.drag_window(self._grab_id,self._grab_rect,dx,dy)
                s.grabbed_window_rect=self.wc.get_active_window_rect() or self._grab_rect
        else:
            if self._r_pin:
                pos=s.r_pinch_pos or (.5,.5); snap=self._snap(pos)
                if snap: self.wc.snap_window(self._grab_id,snap); s.hud_message=f"Snapped {snap}"
                elif pos[0]<.04 or pos[0]>.96:
                    self.wc.fling_to_next_monitor(self._grab_id,"left" if pos[0]<.04 else "right")
                    s.hud_message="Flung!"
                else: s.hud_message="Dropped"
                self._r_pin=False; s.r_pinching=False; s.r_pinch_pos=None
                self._grab_id=self._grab_rect=None; s.hud_snap_zone=None; self._sm.reset()
            self._rps=None

    def _vol(self,lms):
        s=self.s
        if self._pd(lms)<self.cfg["gesture"]["pinch_threshold"]:
            if self._lps is None: self._lps=time.time()
            if (time.time()-self._lps)*1000>300:
                vol=min(1.,max(0.,_d(lms[T4],lms[I8])/.25))
                s.volume_level=vol; s.l_pinching=True
                self.wc.set_volume(vol); s.hud_message=f"Vol {int(vol*100)}%"
        else: s.l_pinching=False; self._lps=None

    def _swipe(self,lms):
        if self._sw_cd>0: return
        px=lms[W].x
        if self._prev_px is not None:
            v=px-self._prev_px
            sv=self.cfg["gesture"]["swipe_velocity"]
            if v<-sv: self.wc.switch_desktop("left"); self.s.hud_message="Desktop <-"; self._sw_cd=25
            elif v>sv: self.wc.switch_desktop("right"); self.s.hud_message="Desktop ->"; self._sw_cd=25
        self._prev_px=px

    def _enter_task(self):
        self._L_cd=90; self._mode="task"
        self._task_wins=self.wc.list_windows()[:5]
        self._num_last=0; self._num_confirm=0
        pyautogui.hotkey("win","tab"); time.sleep(.3)
        names=[f"{i+1}:{w[1][:18]}" for i,w in enumerate(self._task_wins)]
        self.s.hud_message="Show fingers 1-5 to pick  |  fist=cancel  |  "+("  ".join(names))

    def _task_mode(self,r,shape):
        s=self.s
        if not self._task_wins: self._mode="normal"; return
        if r and self._fist(r): self._mode="normal"; pyautogui.press("escape"); s.hud_message="Cancelled"; return

        if r and self._num_cd==0:
            n=_fingers_up(r)
            if n==self._num_last and n>0:
                self._num_confirm+=1
                pct=min(self._num_confirm/8,1.)
                bar="█"*int(pct*10)+"░"*(10-int(pct*10))
                names=[f"{i+1}:{w[1][:14]}" for i,w in enumerate(self._task_wins)]
                s.hud_message=f"[{n}] {bar}  "+("  ".join(names))
                if self._num_confirm>=8:
                    idx=n-1
                    if idx<len(self._task_wins):
                        wid,title=self._task_wins[idx]
                        self.wc.focus_window(wid); time.sleep(.15)
                        pyautogui.press("escape")
                        s.hud_message=f"Active: {title[:40]}"
                    self._mode="normal"; self._num_cd=30; self._num_confirm=0
            else:
                self._num_last=n; self._num_confirm=0
                if n>0:
                    idx=n-1
                    name=self._task_wins[idx][1][:30] if idx<len(self._task_wins) else "?"
                    s.hud_message=f"Hold {n} fingers -> [{name}]"
                else:
                    names=[f"{i+1}:{w[1][:14]}" for i,w in enumerate(self._task_wins)]
                    s.hud_message="1-5 fingers to pick  |  "+"  ".join(names)

    def _pd(self,lms): return _d(lms[T4],lms[I8])/(_d(lms[W],lms[M9]) or .1)
    def _fist(self,lms): return sum(1 for t,m in zip([I8,M12,R16,P20],[5,9,13,17]) if lms[t].y>lms[m].y)>=4
    def _is_L(self,lms):
        return(lms[I8].y<lms[I5].y-.04 and abs(lms[T4].x-lms[W].x)>.12
               and lms[M12].y>lms[M9].y and lms[R16].y>lms[13].y and lms[P20].y>lms[17].y)
    def _snap(self,pos):
        x,y=pos
        if x<.14 and y<.25: return "top-left"
        if x>.86 and y<.25: return "top-right"
        if x<.14 and y>.75: return "bottom-left"
        if x>.86 and y>.75: return "bottom-right"
        if x<.11: return "left-half"
        if x>.89: return "right-half"
        if y<.07: return "full"
        return None
    def _reset(self):
        s=self.s
        s.r_pinching=s.l_pinching=s.both_pinching=s.pointing=False
        s.r_pinch_pos=s.r_drag_delta=s.grabbed_window_id=s.grabbed_window_rect=s.hud_snap_zone=None
        self._r_pin=False; self._grab_id=self._grab_rect=None
        self._rps=self._lps=None; self._sm.reset(); self._mode="normal"

    def _dbg(self,frame,res):
        h,w=frame.shape[:2]; s=self.s
        for z,(x0,y0,x1,y1) in SNAP_ZONES.items():
            if s.hud_snap_zone==z:
                ov=frame.copy()
                cv2.rectangle(ov,(int(x0*w),int(y0*h)),(int(x1*w),int(y1*h)),(0,220,120),-1)
                cv2.addWeighted(ov,.18,frame,.82,0,frame)
                cv2.rectangle(frame,(int(x0*w),int(y0*h)),(int(x1*w),int(y1*h)),(0,220,120),2)
        if res.hand_landmarks:
            for lms in res.hand_landmarks:
                _draw(frame,lms,(0,200,255) if self._r_pin else (0,220,120))
        if self._mode=="task" and self._task_wins:
            wins=self._task_wins; n=len(wins); bw=w//max(n,1)
            for i,(_,name) in enumerate(wins):
                sel=i==(self._num_last-1)
                col=(0,220,120) if sel else (80,80,80)
                cv2.rectangle(frame,(i*bw+2,h-60),((i+1)*bw-2,h-4),col,2 if sel else 1)
                cv2.putText(frame,f"{i+1}",(i*bw+8,h-38),cv2.FONT_HERSHEY_SIMPLEX,.55,col,2,cv2.LINE_AA)
                cv2.putText(frame,name[:max(1,bw//9)],(i*bw+6,h-16),cv2.FONT_HERSHEY_SIMPLEX,.34,col,1,cv2.LINE_AA)
            if self._num_last>0:
                pct=min(self._num_confirm/8,1.)
                bx,by=10,h-72
                cv2.rectangle(frame,(bx,by),(bx+int(160*pct),by+8),(0,220,120),-1)
                cv2.rectangle(frame,(bx,by),(bx+160,by+8),(80,80,80),1)
        if s.r_pinch_pos:
            px,py=int(s.r_pinch_pos[0]*w),int(s.r_pinch_pos[1]*h)
            cv2.circle(frame,(px,py),14,(0,220,120),2); cv2.circle(frame,(px,py),5,(0,220,120),-1)
        col=(0,255,180) if not s.paused else (0,80,255)
        mode_tag="[TASK]" if self._mode=="task" else ""
        cv2.putText(frame,f"{mode_tag} {s.hud_message}",(10,28),cv2.FONT_HERSHEY_SIMPLEX,.56,col,2,cv2.LINE_AA)
        st="PAUSED" if s.paused else("TASK" if self._mode=="task" else("PIN" if self._r_pin else "RDY"))
        cv2.putText(frame,st,(10,52),cv2.FONT_HERSHEY_SIMPLEX,.44,(180,180,180),1,cv2.LINE_AA)
        cv2.putText(frame,f"VOL {int(s.volume_level*100)}%",(10,70),cv2.FONT_HERSHEY_SIMPLEX,.4,(160,160,220),1,cv2.LINE_AA)
