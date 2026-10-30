
"""
Bot interactivo Telegram para Render - v11
Responde /top /ahora /macro /ayuda
Usa mismo motor que daily v11 con anti rate-limit
"""
import os, time, yfinance as yf, pandas as pd, numpy as np, requests, pytz
from datetime import datetime
from xml.etree import ElementTree
import telebot

TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)

TICKERS_BMV = ["AAPL","AC","AMXB","AMZN","BBVA","BIMBOA","CEMEXCPO","CUERVO","F","FIBRAMQ12","FMTY14","GAPB","GCARSOA1","GFINBURO","GFNORTEO","GMEXICOB","GOOGL","GRUMAB","HERDEZ","IEO","INTC","IVVPESO","KIMBERA","KOFUBL","META","MSFT","NAFTRAC","NEMAKA","NFLX","NOKN","NVDA","PINFRA","SLV","SORIANAB","TLEVISACPO","TM","TSLA","VOLARA","WALMEX"]
MAP = {t: f"{t}.MX" for t in TICKERS_BMV}
MAP["IVVPESO"]="IVVPESOISHRS.MX"
MAP["NAFTRAC"]="NAFTRACISHRS.MX"

def rsi(s,p=14):
    d=s.diff(); g=d.where(d>0,0).rolling(p).mean(); l=-d.where(d<0,0).rolling(p).mean()
    rs=g/l.replace(0,np.nan); return 100-(100/(1+rs))

def get_macro():
    tz=pytz.timezone('America/Mexico_City'); now=datetime.now(tz)
    estado={"usd_pct":0.0,"ipc_pct":0.0,"ipc_tipo":"cierre_ayer","nivel":"NORMAL","msg":"","bloqueo":False,"fuente":""}
    try:
        u=yf.Ticker("USDMXN=X"); hd=u.history(period="5d", interval="1d")
        if len(hd)>=2: estado["usd_pct"]=(float(hd['Close'].iloc[-1])-float(hd['Close'].iloc[-2]))/float(hd['Close'].iloc[-2])*100
        hi=u.history(period="1d", interval="5m")
        if len(hi)>=2: estado["usd_pct"]=(float(hi['Close'].iloc[-1])-float(hi['Close'].iloc[0]))/float(hi['Close'].iloc[0])*100
    except: pass
    try:
        ipc=yf.Ticker("^MXX"); hd=ipc.history(period="5d", interval="1d")
        if len(hd)>=2:
            last_date=hd.index[-1].date(); prev=float(hd['Close'].iloc[-2]); last_c=float(hd['Close'].iloc[-1]); last_o=float(hd['Open'].iloc[-1])
            if last_date==now.date() and last_o!=0:
                estado["ipc_pct"]=(last_o-prev)/prev*100; estado["ipc_tipo"]="open_hoy_daily"; estado["fuente"]=f"open {last_o:.1f}"
            else:
                hi=ipc.history(period="1d", interval="1m")
                if len(hi)>0:
                    oi=float(hi['Open'].iloc[0]); cy=float(hd['Close'].iloc[-1])
                    estado["ipc_pct"]=(oi-cy)/cy*100; estado["ipc_tipo"]="open_hoy_intraday"
                else:
                    estado["ipc_pct"]=(last_c-prev)/prev*100
    except: estado["ipc_tipo"]="error"
    usd=estado["usd_pct"]; ipc=estado["ipc_pct"]
    if ipc<=-0.76: estado["nivel"]="EXTREMO"; estado["bloqueo"]=True; estado["msg"]=f"IPC {ipc:.2f}% muy rojo"
    elif ipc<=-0.40: estado["nivel"]="ALTO"; estado["msg"]=f"IPC {ipc:.2f}% rojo"
    if usd>=0.8: estado["nivel"]="EXTREMO"; estado["bloqueo"]=True; estado["msg"]+=f" USD/MXN +{usd:.2f}% EXTREMO."
    elif usd>=0.58: estado["msg"]+=f" USD/MXN +{usd:.2f}% alto."
    if not estado["msg"]: estado["msg"]=f"Normal USD {usd:.2f}% IPC {ipc:.2f}%"
    return estado

def evaluar(base,macro):
    yahoo=MAP[base]
    try:
        tk=yf.Ticker(yahoo); h=tk.history(period="3mo", interval="1d")
        if len(h)<35: return {"ticker":yahoo,"bloqueado":f"Sin hist"}
        close=h['Close']; vol=h['Volume']
        price=float(close.iloc[-1]); prev=float(close.iloc[-2]); open_hoy=float(h['Open'].iloc[-1])
        gap=(open_hoy-prev)/prev*100; vol_mean=float(vol.rolling(20).mean().iloc[-1]); vr=float(vol.iloc[-1]/vol_mean) if vol_mean>0 else 1
        r=float(rsi(close).iloc[-1])
        if r>78: return {"ticker":yahoo,"bloqueado":f"RSI {r:.0f}"}
        if vr<0.6: return {"ticker":yahoo,"bloqueado":f"Vol {vr:.1f}x"}
        if abs(gap)>5: return {"ticker":yahoo,"bloqueado":f"Gap {gap:.1f}%"}
        prob_base=40.9+(r-50)*-0.18+(vr-1)*6; ret5=(close.iloc[-1]/close.iloc[-6]-1)*100; prob_base+=max(min(ret5*0.4,4),-4)
        prob_base=float(max(min(prob_base,68),36)); prob=prob_base
        if macro["usd_pct"]>=0.7: prob-=7
        if macro["ipc_pct"]<=-0.40: prob-=6
        prob=float(max(min(prob,70),28))
        return {"ticker":yahoo,"base":base,"price":price,"venta":price*1.012,"stop":price*0.992,"rsi":r,"vol":vr,"prob_base":prob_base,"prob":prob,"bloqueado":None}
    except Exception as e:
        return {"ticker":yahoo,"bloqueado":f"Error {str(e)[:50]}"}

def construir(resultados,bloqueados,macro):
    hoy=datetime.now(pytz.timezone('America/Mexico_City')).strftime('%Y-%m-%d %H:%M')
    txt=f"📊 <b>TOP BMV HOY {hoy} v11 - FILTRO IPC OPEN FIX</b>\nTasa base: 40.9% | Evaluadas: {len(resultados)+len(bloqueados)}/40 | Comprables: {len(resultados)}\nMacro: {macro['nivel']} | {macro['msg']}\nUSD/MXN: {macro['usd_pct']:.2f}% | IPC: {macro['ipc_pct']:.2f}% ({macro['ipc_tipo']})\n\n"
    if macro['bloqueo']: txt+=f"🚫 <b>HOY NO OPERES</b> {macro['msg']}\n\n"
    top=sorted([r for r in resultados if not r.get('bloqueado')], key=lambda x: x['prob'], reverse=True)[:10]
    for i,r in enumerate(top,1):
        ico="✅" if r['prob']>=60 else "👀"
        link=f"https://www.google.com/finance/quote/{r['base']}:BMV"
        txt+=f"{i}. {ico} <a href='{link}'><b>{r['ticker']}</b></a> {r['prob']:.1f}% | ${r['price']:.2f} V ${r['venta']:.2f} S ${r['stop']:.2f}\n"
    return txt[:4000]

@bot.message_handler(commands=['top','ahora','macro','ayuda','start'])
def handle(m):
    cmd=m.text.lower()
    if '/ayuda' in cmd or '/start' in cmd:
        bot.reply_to(m, "Comandos:\n/top - TOP 10 del dia\n/ahora - recalcula ahora\n/macro - solo macro USD e IPC\n/ayuda - este mensaje", parse_mode="HTML")
        return
    if '/macro' in cmd:
        macro=get_macro()
        bot.reply_to(m, f"Macro {macro['nivel']}\nUSD {macro['usd_pct']:.2f}% IPC {macro['ipc_pct']:.2f}% ({macro['ipc_tipo']})\n{macro['msg']}")
        return
    bot.reply_to(m, "⏳ Calculando TOP 10 v11 con filtro IPC OPEN FIX...")
    macro=get_macro(); res=[]; bloq=[]
    for b in TICKERS_BMV:
        r=evaluar(b,macro); time.sleep(0.5)
        (res if not r.get('bloqueado') else bloq).append(r)
    msg=construir(res,bloq,macro)
    bot.send_message(m.chat.id, msg, parse_mode="HTML", disable_web_page_preview=True)

print("Bot interactivo v11 iniciado")
bot.infinity_polling()
