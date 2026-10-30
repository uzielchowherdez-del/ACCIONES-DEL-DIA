
"""
BMV Bot Daily v11.2 - FINAL con anti rate-limit + IPC OPEN FIX
"""
import yfinance as yf, pandas as pd, numpy as np, requests, os, time, pytz
from datetime import datetime
from xml.etree import ElementTree

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TICKERS_BMV = ["AAPL","AC","AMXB","AMZN","BBVA","BIMBOA","CEMEXCPO","CUERVO","F","FIBRAMQ12","FMTY14","GAPB","GCARSOA1","GFINBURO","GFNORTEO","GMEXICOB","GOOGL","GRUMAB","HERDEZ","IEO","INTC","IVVPESO","KIMBERA","KOFUBL","META","MSFT","NAFTRAC","NEMAKA","NFLX","NOKN","NVDA","PINFRA","SLV","SORIANAB","TLEVISACPO","TM","TSLA","VOLARA","WALMEX"]
# PE&OLES lo dejamos fuera del loop auto para evitar crash & -> se evalua como bloqueado
MAP = {t: f"{t}.MX" for t in TICKERS_BMV}
MAP["IVVPESO"] = "IVVPESOISHRS.MX"
MAP["NAFTRAC"] = "NAFTRACISHRS.MX"

def rsi(s, p=14):
    d=s.diff(); g=d.where(d>0,0).rolling(p).mean(); l=-d.where(d<0,0).rolling(p).mean()
    rs=g/l.replace(0,np.nan); return 100-(100/(1+rs))

def get_news(t):
    try:
        url=f"https://news.google.com/rss/search?q={t}+BMV&hl=es-419&gl=MX&ceid=MX:es-419"
        r=requests.get(url, timeout=5, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200:
            root=ElementTree.fromstring(r.content)
            it=root.findall('.//item')[:1]
            if it:
                title=it[0].find('title').text or ""
                low=title.lower()
                score=0
                if any(k in low for k in ["alza","sube","record","ganancia","fuerte"]): score=2
                if any(k in low for k in ["cae","baja","perdida","peor"]): score=-2
                return score, title[:120]
    except: pass
    return 0,""

def get_macro():
    tz=pytz.timezone('America/Mexico_City'); now=datetime.now(tz)
    estado={"usd_pct":0.0,"ipc_pct":0.0,"ipc_tipo":"cierre_ayer","nivel":"NORMAL","msg":"","bloqueo":False,"fuente":""}
    # USD
    try:
        u=yf.Ticker("USDMXN=X")
        hd=u.history(period="5d", interval="1d")
        if len(hd)>=2:
            estado["usd_pct"]=(float(hd['Close'].iloc[-1])-float(hd['Close'].iloc[-2]))/float(hd['Close'].iloc[-2])*100
        hi=u.history(period="1d", interval="5m")
        if len(hi)>=2:
            estado["usd_pct"]=(float(hi['Close'].iloc[-1])-float(hi['Close'].iloc[0]))/float(hi['Close'].iloc[0])*100
    except Exception as e:
        print("USD err",e)
    # IPC OPEN HOY FIX
    try:
        ipc=yf.Ticker("^MXX")
        hd=ipc.history(period="5d", interval="1d")
        if len(hd)>=2:
            last_date=hd.index[-1].date()
            prev=float(hd['Close'].iloc[-2]); last_c=float(hd['Close'].iloc[-1]); last_o=float(hd['Open'].iloc[-1])
            if last_date==now.date() and last_o!=0:
                estado["ipc_pct"]=(last_o-prev)/prev*100; estado["ipc_tipo"]="open_hoy_daily"; estado["fuente"]=f"open {last_o:.1f} vs {prev:.1f}"
            else:
                hi=ipc.history(period="1d", interval="1m")
                if len(hi)>0:
                    oi=float(hi['Open'].iloc[0]); cy=float(hd['Close'].iloc[-1])
                    estado["ipc_pct"]=(oi-cy)/cy*100; estado["ipc_tipo"]="open_hoy_intraday"; estado["fuente"]=f"intra open {oi:.1f} vs {cy:.1f}"
                else:
                    estado["ipc_pct"]=(last_c-prev)/prev*100; estado["ipc_tipo"]="cierre_ayer"
    except Exception as e:
        print("IPC err",e); estado["ipc_tipo"]="error"
    usd=estado["usd_pct"]; ipc=estado["ipc_pct"]
    if ipc<=-0.76: estado["nivel"]="EXTREMO"; estado["bloqueo"]=True; estado["msg"]=f"🚫 IPC {ipc:.2f}% muy rojo - HOY NO OPERES."
    elif ipc<=-0.40: estado["nivel"]="ALTO"; estado["msg"]=f"⚠️ IPC {ipc:.2f}% rojo"
    if usd>=0.8: estado["nivel"]="EXTREMO"; estado["bloqueo"]=True; estado["msg"]+=f" USD/MXN +{usd:.2f}% EXTREMO."
    elif usd>=0.58:
        if estado["nivel"]=="NORMAL": estado["nivel"]="ALTO"
        estado["msg"]+=f" USD/MXN +{usd:.2f}% alto."
    if usd>=0.5 and ipc<=-0.3: estado["nivel"]="EXTREMO"; estado["bloqueo"]=True; estado["msg"]+=" 💥 Combo USD↑ + IPC↓."
    if not estado["msg"]: estado["msg"]=f"Día normal USD {usd:.2f}% IPC {ipc:.2f}%"
    return estado

def evaluar(base, macro):
    yahoo=MAP[base]
    for intento in range(2):
        try:
            tk=yf.Ticker(yahoo)
            h=tk.history(period="3mo", interval="1d")
            if len(h)<35:
                return {"ticker":yahoo,"bloqueado":f"Sin hist {len(h)}"}
            close=h['Close']; vol=h['Volume']
            price=float(close.iloc[-1]); prev=float(close.iloc[-2]); open_hoy=float(h['Open'].iloc[-1])
            gap=(open_hoy-prev)/prev*100
            vol_mean=float(vol.rolling(20).mean().iloc[-1]); vr=float(vol.iloc[-1]/vol_mean) if vol_mean>0 else 1
            r=float(rsi(close).iloc[-1])
            if r>78: return {"ticker":yahoo,"bloqueado":f"RSI {r:.0f} sobrecompra"}
            if r<22: return {"ticker":yahoo,"bloqueado":f"RSI {r:.0f} sobreventa"}
            if vr<0.6: return {"ticker":yahoo,"bloqueado":f"Vol {vr:.1f}x bajo"}
            if abs(gap)>5: return {"ticker":yahoo,"bloqueado":f"Gap {gap:.1f}%"}
            prob_base=40.9+(r-50)*-0.18+(vr-1)*6
            ret5=(close.iloc[-1]/close.iloc[-6]-1)*100
            prob_base+=max(min(ret5*0.4,4),-4)
            prob_base=float(max(min(prob_base,68),36))
            prob=prob_base
            if macro["usd_pct"]>=0.7: prob-=7
            if macro["usd_pct"]>=0.8: prob-=5
            if macro["usd_pct"]<=-0.7: prob+=4
            if macro["ipc_pct"]<=-0.40: prob-=6
            if macro["ipc_pct"]<=-0.76: prob-=10
            score,txt=get_news(base)
            if score==2: prob+=3
            if score==-2: prob-=6
            prob=float(max(min(prob,70),28))
            return {"ticker":yahoo,"base":base,"price":price,"venta":price*1.012,"stop":price*0.992,"rsi":r,"vol":vr,"gap":gap,"prob_base":prob_base,"prob":prob,"news":txt,"bloqueado":None}
        except Exception as e:
            msg=str(e)
            if "Too Many Requests" in msg or "429" in msg:
                print(f"Rate limit {base}, esperando 12s intento {intento}")
                time.sleep(12); continue
            return {"ticker":yahoo,"bloqueado":f"Error {msg[:60]}"}
    return {"ticker":yahoo,"bloqueado":"Rate limit persistente"}

def send_tg(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Falta TOKEN/CHAT"); print(text[:2000]); return
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=15)
    except Exception as e:
        print(e)

def construir(resultados,bloqueados,macro):
    from datetime import datetime
    import pytz
    hoy=datetime.now(pytz.timezone('America/Mexico_City')).strftime('%Y-%m-%d')
    txt=f"📊 <b>TOP BMV HOY {hoy} v11 - FILTRO IPC OPEN FIX</b>\nTasa base: 40.9% | Evaluadas: {len(resultados)+len(bloqueados)}/40 | Comprables: {len(resultados)}\nMacro: {macro['nivel']} | {macro['msg']}\nUSD/MXN: {macro['usd_pct']:.2f}% | IPC: {macro['ipc_pct']:.2f}% ({macro['ipc_tipo']})\nFuente: {macro['fuente']}\n\n"
    if macro['bloqueo']:
        txt+=f"🚫 <b>HOY NO OPERES - MERCADO EN ROJO</b>\nMotivo: {macro['msg']}\nSi operas hoy, prob real cae a <35%. Mejor esperar mañana.\n\n"
    top=sorted([r for r in resultados if not r.get('bloqueado')], key=lambda x: x['prob'], reverse=True)[:10]
    if top:
        txt+="<b>TOP 10 COMPRABLES HOY:</b>\n"
        for i,r in enumerate(top,1):
            ico="👀"; 
            if r['prob']>=60: ico="✅"
            link=f"https://www.google.com/finance/quote/{r['base']}:BMV"
            txt+=f"{i}. {ico} <a href='{link}'><b>{r['ticker']}</b></a> {r['prob']:.1f}% (base {r['prob_base']:.1f}%) | ${r['price']:.2f} | Venta ${r['venta']:.2f} | Stop ${r['stop']:.2f} | RSI {r['rsi']:.0f} Vol {r['vol']:.1f}x\n"
            if r['news']: txt+=f"   📰 [RSS {r['base']}] {r['news'][:110]}\n\n"
    else:
        txt+="Sin oportunidades comprables hoy.\n"
        if bloqueados: txt+=f"Top bloqueados: {', '.join([b['ticker']+ ' '+b['bloqueado'][:35] for b in bloqueados[:3]])}\n\n"
    txt+="🔗 Click en ticker abre Google Finance\n⚠️ Hey sin stop auto. Alerta TradingView en Stop.\n\nComandos: /top /ahora /macro /ayuda"
    return txt[:4000]

def main():
    try:
        macro=get_macro()
        res=[]; bloq=[]
        for b in TICKERS_BMV:
            r=evaluar(b,macro)
            time.sleep(0.6)  # anti rate limit
            if r.get('bloqueado'): bloq.append(r)
            else: res.append(r)
        # agregar PE&OLES bloqueado manual para no crashear
        bloq.append({"ticker":"PE&OLES.MX","bloqueado":"Ticker con & - evaluar manual en Google Finance"})
        msg=construir(res,bloq,macro)
        send_tg(msg)
    except Exception as e:
        import traceback; err=traceback.format_exc()[-1500:]
        send_tg(f"❌ Bot v11 fallo {e}\n{err}")

if __name__=="__main__":
    main()
