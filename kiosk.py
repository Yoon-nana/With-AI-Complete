"""카페 매장 형태의 Tkinter 키오스크. main.py로 실행합니다."""
import json
import logging
from pathlib import Path
import queue
import tkinter as tk
from core import MENUS, Session
from guidance import load_guidance

BASE = Path(__file__).resolve().parent
BG, INK, GREEN, MUTED = "#f7f5f0", "#202b27", "#185542", "#66746c"
TITLES = {"start": "오늘도, 편안하게 한 잔", "service_mode": "어디에서 드시나요?", "menu": "어떤 음료를 드릴까요?", "options": "취향에 맞게 골라주세요", "confirm": "주문 내역을 확인해주세요", "complete": "주문 연습이 완료됐어요"}

class App:
    def __init__(self, root, worker):
        self.root, self.worker = root, worker
        self.state = Session()
        self.guidance = load_guidance(BASE / "data" / "guidance.json")
        self.current_guidance, self.category = "", "전체"
        self.selection_buttons = []
        self.fullscreen = self.closing = False
        root.title("ROBO CAFE · 키오스크 주문 연습")
        root.geometry(f"{min(1240, root.winfo_screenwidth()-40)}x{min(900, root.winfo_screenheight()-80)}")
        root.minsize(900, 650)
        root.configure(bg=BG)
        root.option_add("*Font", ("맑은 고딕", 15))
        root.bind("<F11>", lambda e: self.toggle_fullscreen())
        root.bind("<Escape>", lambda e: self.set_fullscreen(False))
        header = tk.Frame(root, bg=GREEN, padx=26, pady=14)
        header.pack(fill="x")
        tk.Label(header, text="ROBO CAFE", font=("맑은 고딕", 26, "bold"), fg="white", bg=GREEN).pack(side="left")
        tk.Label(header, text="카페 주문 연습\n실제 주문·결제 없음", fg="white", bg=GREEN, justify="right", font=("맑은 고딕", 12)).pack(side="right")
        self.progress = tk.Label(root, bg="#e9ede7", fg=GREEN, pady=9, font=("맑은 고딕", 13, "bold"))
        self.progress.pack(fill="x")
        bottom = tk.Frame(root, bg="white", padx=18, pady=10)
        bottom.pack(side="bottom", fill="x")
        self.guide = tk.StringVar()
        tk.Label(bottom, textvariable=self.guide, bg="#edf4ef", fg=GREEN, anchor="w", justify="left", wraplength=820, padx=14, pady=9, font=("맑은 고딕", 14)).pack(fill="x", pady=(0,7))
        helpers = tk.Frame(bottom, bg="white")
        helpers.pack(fill="x")
        self.back_button = self.button(helpers, "← 이전 단계", self.back)
        self.back_button.pack(side="left", padx=3)
        for text, command in (("힌트", self.help_request), ("도움 요청", self.help_request), ("다시 안내", self.repeat)):
            self.button(helpers, text, command).pack(side="left", padx=3)
        self.button(helpers, "전체 화면", self.toggle_fullscreen).pack(side="right")
        tools = tk.Frame(bottom, bg="white")
        tools.pack(fill="x", pady=(6,0))
        self.status = tk.StringVar(value="로보독 연결 준비 중…")
        tk.Label(tools, textvariable=self.status, bg="white", fg=MUTED, anchor="w", wraplength=620, font=("맑은 고딕",10)).pack(side="left", fill="x", expand=True)
        for text, action in (("소리 시험", "SOUND_TEST"), ("애교 시험", "GESTURE_TEST")):
            self.button(tools, text, lambda a=action: worker.submit(a), small=True).pack(side="right", padx=3)
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True)
        self.cart = tk.Frame(body, bg="#e9ede7", width=255, padx=18, pady=20)
        self.cart.pack(side="right", fill="y")
        self.cart.pack_propagate(False)
        main = tk.Frame(body, bg=BG, padx=22, pady=14)
        main.pack(side="left", fill="both", expand=True)
        self.title = tk.Label(main, bg=BG, fg=INK, font=("맑은 고딕",23,"bold"), anchor="w")
        self.title.pack(fill="x")
        self.subtitle = tk.Label(main, bg=BG, fg=MUTED, font=("맑은 고딕",12), anchor="w")
        self.subtitle.pack(fill="x", pady=(4,10))
        self.canvas = tk.Canvas(main, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(main, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = tk.Frame(self.canvas, bg=BG)
        self.content_window = self.canvas.create_window(0,0,window=self.content,anchor="nw")
        self.content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.content_window,width=e.width))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.render()
        root.after(100,self.poll)

    def button(self, parent, text, command, primary=False, small=False):
        b = tk.Button(parent,text=text,command=command,takefocus=True,bg=GREEN if primary else "white",fg="white" if primary else INK,activebackground="#d8e8dc",activeforeground=INK,relief="flat",padx=14,pady=7 if small else 12,font=("맑은 고딕",10 if small else 15,"bold"))
        b.bind("<Return>",lambda e:b.invoke())
        b.bind("<FocusIn>",lambda e:self.reveal(b))
        return b

    def reveal(self, widget):
        if not str(widget).startswith(str(self.content)):
            return
        self.root.update_idletasks()
        y = widget.winfo_rooty()-self.content.winfo_rooty()
        if y < self.canvas.canvasy(0) or y+widget.winfo_height()>self.canvas.canvasy(self.canvas.winfo_height()):
            self.canvas.yview_moveto(max(0,(y-15)/max(1,self.content.winfo_height())))

    def row(self,text,command,primary=False):
        b=self.button(self.content,text,command,primary)
        b.pack(fill="x",pady=6)
        return b

    def show_message(self,text,action=None):
        self.current_guidance=text
        self.guide.set(text)
        if action:self.worker.submit(action)

    def describe(self):
        item=self.guidance[self.state.screen]
        if self.state.support_level==3:
            field={"service_mode":"service","menu":"menu","options":"temperature"}.get(self.state.screen)
            index=1 if field and field in self.state.order else 0
            return item["steps"][min(index,len(item["steps"])-1)]
        return item["hint"] if self.state.support_level==2 else item["intro"]

    def draw_drink(self,parent,key):
        c=tk.Canvas(parent,width=160,height=105,bg="white",highlightthickness=0)
        c.pack(pady=(12,2))
        color={"americano":"#593c2d","latte":"#c9a477","tea":"#b98c40","juice":"#eca348","vanilla":"#b89972","honey":"#976c36","strawberry_latte":"#efbacb","peach_tea":"#c87d36"}[key]
        c.create_oval(24,91,140,105,fill="#eeece6",outline="")
        c.create_polygon(42,20,122,20,113,90,52,90,fill=color,outline="#ded8cb",width=2)
        c.create_polygon(46,43,119,43,115,75,50,75,fill="#f7f0e4",outline="")
        c.create_text(82,58,text="ROBO",fill=GREEN,font=("Arial",11,"bold"))
        c.create_oval(41,13,123,28,fill="#f2e2c6",outline="#ded8cb",width=2)
        if key=="juice":c.create_line(93,21,105,1,fill="#688b6a",width=5)
        else:c.create_oval(46,16,118,24,fill=color,outline="")

    def menu_cards(self):
        tabs=tk.Frame(self.content,bg=BG)
        tabs.pack(fill="x",pady=(0,12))
        for category in ("전체","커피","차·주스"):
            self.button(tabs,category,lambda v=category:self.filter_menu(v),self.category==category).pack(side="left",padx=(0,8))
        grid=tk.Frame(self.content,bg=BG)
        grid.pack(fill="x")
        for col in (0,1):grid.columnconfigure(col,weight=1,uniform="menu")
        items=list(MENUS.items())
        if self.state.variant:items.reverse()
        items=[(k,d) for k,d in items if self.category=="전체" or (self.category=="커피")== (k not in ("tea","juice"))]
        for index,(key,data) in enumerate(items):
            selected=self.state.order.get("menu")==key
            card=tk.Frame(grid,bg="white",highlightthickness=3,highlightbackground=GREEN if selected else "#e5e5dc")
            card.grid(row=index//2,column=index%2,sticky="nsew",padx=5,pady=5)
            self.draw_drink(card,key)
            b=self.button(card,("✓ 선택됨  " if selected else "")+data[0]+f"\n{data[1]:,}원",lambda v=key:self.choose(self.state.choose_menu,v))
            b.pack(fill="x",padx=5,pady=(0,8))
            self.selection_buttons.append(b)

    def filter_menu(self,value):
        self.category=value
        self.render(False)

    def render(self,announce=True):
        for w in self.content.winfo_children():w.destroy()
        self.selection_buttons=[]
        s=self.state.screen
        self.title.config(text=TITLES[s])
        self.subtitle.config(text="기초 도전 · 메뉴 배치가 달라졌어요" if self.state.variant else "천천히 골라도 괜찮아요. 언제든 도움을 요청하세요.")
        steps=("service_mode","menu","options","confirm","complete")
        names=("이용 방식","메뉴 선택","옵션 선택","주문 확인","완료")
        self.progress.config(text="   →   ".join(("● " if step==s else "")+name for step,name in zip(steps,names)))
        self.back_button.config(state="disabled" if s in ("start","complete") else "normal")
        if s=="start":
            self.draw_drink(self.content,"latte")
            tk.Label(self.content,text="로보독과 함께하는\n나만의 카페 주문 연습",bg=BG,fg=GREEN,font=("맑은 고딕",24,"bold"),pady=22).pack()
            self.row("안내를 보며 배우기",lambda:self.start("guided"),True)
            self.row("혼자 해보기",lambda:self.start("practice"))
        elif s=="service_mode":
            self.choices([("매장에서 먹기","매장에서 먹기\n매장 안에서 편안하게"),("가져가기","가져가기\n포장해서 가져갈게요")],"service",self.state.choose_service)
            self.next_button("menu","service")
        elif s=="menu":
            self.menu_cards()
            self.next_button("options","menu")
        elif s=="options":
            key=self.state.order["menu"]
            self.draw_drink(self.content,key)
            tk.Label(self.content,text=MENUS[key][0],bg=BG,fg=INK,pady=10,font=("맑은 고딕",20,"bold")).pack()
            options=MENUS[key][2]
            self.choices([(v,v) for v in options],"temperature",self.state.choose_temperature)
            self.row(f"기본값으로 계속 ({options[0]})",self.default_option)
            self.next_button("confirm","temperature")
        elif s=="confirm":
            o=self.state.order
            tk.Label(self.content,text=f"{o['service']}\n\n{MENUS[o['menu']][0]}  1잔\n{o['temperature']}\n\n총 {MENUS[o['menu']][1]:,}원",justify="left",bg="white",fg=INK,padx=25,pady=24,font=("맑은 고딕",20)).pack(fill="x",pady=10)
            self.row("주문 연습 완료 · 결제 없음",self.finish,True)
            self.row("메뉴 다시 고르기",lambda:self.navigate("menu"))
            self.row("옵션 다시 고르기",lambda:self.navigate("options"))
        else:
            tk.Label(self.content,text="✓\n잘하셨어요!",bg=BG,fg=GREEN,font=("맑은 고딕",40,"bold"),pady=20).pack()
            tk.Label(self.content,text=f"실제 결제는 진행되지 않았어요.\n이번 과제 도움 요청 {self.state.help_count}회",bg=BG,fg=MUTED,pady=8).pack()
            self.row("같은 과제 다시 연습",lambda:self.start(variant=self.state.variant),True)
            self.row("다른 화면으로 도전",lambda:self.start(variant=True))
            self.row("처음으로",lambda:self.navigate("start"))
        self.render_cart()
        if announce:self.show_message(self.describe(),"WELCOME" if s=="start" else "INTRO")
        self.canvas.yview_moveto(0)
        if self.selection_buttons:self.selection_buttons[0].focus_set()

    def render_cart(self):
        for w in self.cart.winfo_children():w.destroy()
        tk.Label(self.cart,text="나의 주문",bg="#e9ede7",fg=GREEN,font=("맑은 고딕",20,"bold")).pack(anchor="w",pady=(0,20))
        o=self.state.order
        for text in (o.get("service","이용 방식을 골라주세요"),MENUS[o["menu"]][0] if "menu" in o else "음료를 골라주세요",o.get("temperature","온도 선택 전")):
            tk.Label(self.cart,text=text,bg="#e9ede7",fg=INK,anchor="w",wraplength=215,justify="left",pady=8).pack(fill="x")
        total=MENUS[o["menu"]][1] if "menu" in o else 0
        tk.Label(self.cart,text=f"주문 금액\n{total:,}원",bg="#e9ede7",fg=GREEN,justify="left",font=("맑은 고딕",23,"bold"),pady=20).pack(anchor="w")
        tk.Label(self.cart,text="연습용 가상 가격\n실제 결제 없음",bg="#e9ede7",fg=MUTED,font=("맑은 고딕",12),justify="left").pack(anchor="w")

    def choices(self,items,field,setter):
        for value,label in items:
            selected=self.state.order.get(field)==value
            b=self.row(("✓ 선택됨  " if selected else "")+label,lambda v=value:self.choose(setter,v),selected)
            self.selection_buttons.append(b)

    def choose(self,setter,value):
        try:
            setter(value)
            self.render(False)
            self.show_message(self.describe())
            self.highlight(True)
        except ValueError as error:self.show_message(str(error))

    def next_button(self,target,field):
        self.next_widget=self.row("다음 →",lambda:self.advance(target),True)
        self.next_widget.config(state="normal" if field in self.state.order else "disabled")

    def highlight(self,next_step=False):
        for b in self.selection_buttons:b.config(highlightbackground=GREEN,highlightthickness=2)
        if next_step and hasattr(self,"next_widget") and self.next_widget.winfo_exists():
            self.next_widget.config(text="다음 → (선택 완료)")
            self.next_widget.focus_set()

    def start(self,mode=None,variant=False):
        self.state.new_task(mode,variant)
        self.category="전체"
        self.render()

    def navigate(self,target):
        try:
            self.state.navigate(target)
            self.render()
            return True
        except ValueError as error:
            self.show_message(str(error))
            return False

    def advance(self,target):
        if self.navigate(target):
            self.worker.submit("PRAISE")
            self.show_message("잘 선택했어요! "+self.describe())

    def default_option(self):
        self.state.choose_temperature()
        self.advance("confirm")

    def back(self):
        self.state.back()
        self.render()

    def help_request(self):
        if self.state.screen not in ("start","complete"):self.state.request_help()
        self.show_message(self.describe(),"STEP_GUIDE" if self.state.support_level==3 else "HINT")
        self.highlight()

    def repeat(self):
        self.guide.set(self.current_guidance)
        self.worker.submit("HINT")

    def finish(self):
        try:record=self.state.complete()
        except ValueError as error:
            self.show_message(str(error))
            return
        if record is None:return
        self.render(False)
        self.show_message(self.guidance["complete"]["intro"],"SUCCESS")
        try:
            with (BASE/"data"/"results.jsonl").open("a",encoding="utf-8") as stream:
                stream.write(json.dumps(record,ensure_ascii=False)+"\n")
        except OSError:
            logging.exception("학습 기록 저장 실패")
            self.show_message("연습은 완료됐지만 기록을 저장하지 못했어요.")

    def poll(self):
        try:
            while True:
                kind,value=self.worker.events.get_nowait()
                if kind in ("status","warning"):self.status.set(value)
                elif not self.worker.available:self.status.set(f"모의 모드 · 실제 로봇 미연결 · 최근 반응 {value}")
        except queue.Empty:pass
        if not self.closing:self.root.after(100,self.poll)

    def toggle_fullscreen(self):self.set_fullscreen(not self.fullscreen)

    def set_fullscreen(self,enabled):
        self.fullscreen=enabled
        self.root.attributes("-fullscreen",enabled)

    def close(self):
        if self.closing:return
        self.closing=True
        self.worker.stop()
        self.status.set("로보독 동작과 연결을 정리하고 있어요…")
        self.wait_closed()

    def wait_closed(self):
        if self.worker.thread.is_alive():self.root.after(100,self.wait_closed)
        else:self.root.destroy()
