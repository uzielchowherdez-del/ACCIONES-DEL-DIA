"""
BMV Bot Telegram Daily v11 - FILTRO IPC OPEN HOY FIX
Fix audit 29-Oct-2026: antes usaba cierre_ayer vs anteayer para IPC, ahora usa OPEN HOY vs CLOSE AYER.
- Tickers: 40 .MX
- Filtros: RSI >78 <22, Vol <0.6x, Gap >5%
- Macro: USD/MXN +0.8% / +0.7% y IPC open hoy -0.40% / -0.76%
- Links Google Finance https://www.google.com/finance/quote/TICKER:BMV
- Comandos: /top /ahora /macro /ayuda
"""
import yfinance as yf
import pandas as pd
import numpy as np
import requests, os, re, time
from datetime import datetime, timedelta
import pytz
from xml.etree import ElementTree

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TICKERS_BMV = ["AAPL","AC","AMXB","AMZN","BBVA","BIMBOA","CEMEXCPO","CUERVO","F","FIBRAMQ12","FMTY14","GAPB","GCARSOA1","GFINBURO","GFNORTEO","GMEXICOB","GOOGL","GRUMAB","HERDEZ","IEO","INTC","IVVPESO","KIMBERA","KOFUBL","META","MSFT","NAFTRAC","NEMAKA","NFLX","NOKN","NVDA","PE&OLES","PINFRA","SLV","SORIANAB","TLEVISACPO","TM","TSLA","VOLARA","WALMEX"]
MAP_YAHOO = {}
for t in TICKERS_BMV:
    if t == "PE&OLES":
        MAP_YAHOO[t] = "PE&OLES.MX"
    elif t == "IVVPESO":
        MAP_YAHOO[t] = "IVVPESOISHRS.MX"
    elif t == "NAFTRAC":
        MAP_YAHOO[t] = "NAFTRACISHRS.MX"
    else:
        MAP_YAHOO[t] = f"{t}.MX"

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta>0,0).rolling(period).mean()
    loss = -delta.where(delta<0,0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100/(1+rs))

def get_google_link(yahoo_ticker):
    base = yahoo_ticker.replace(".MX","").replace("ISHRS","").replace("&","")
    # Google Finance: https://www.google.com/finance/quote/BASE:BMV
    return f"https://www.google.com/finance/quote/{base}:BMV"

def get_news(ticker_base):
    try:
        q = f"{ticker_base} BMV acciones"
        url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=MX&ceid=MX:es-419"
        r = requests.get(url, timeout=6, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200:
            root = ElementTree.fromstring(r.content)
            items = root.findall('.//item')[:2]
            if items:
                t = items[0].find('title').text or ""
                lower = t.lower()
                score = 0
                if any(k in lower for k in ["record","alza","sube","ganancia","fuerte","positivo","crece","rally","maximo"]): score = 2
                if any(k in lower for k in ["cae","baja","perdida","peor","caida","recorta","debil","pierde"]): score = -2
                return score, t[:120]
    except: pass
    return 0, ""

def get_macro_state_v11():
    """
    v11 FIX CRÍTICO: 
    Antes: ipc_pct = (close_ayer - close_anteayer)/close_anteayer  -> dato de ayer, no sirve a las 8:41 AM
    Ahora: ipc_pct = (open_hoy - close_ayer)/close_ayer -> dato real de hoy al abrir
    """
    tz_mx = pytz.timezone('America/Mexico_City')
    now = datetime.now(tz_mx)
    estado = {
        "usd_pct": 0.0,
        "ipc_pct": 0.0,
        "ipc_tipo": "cierre_ayer_fallback",
        "nivel": "NORMAL",
        "msg": "",
        "bloqueo": False,
        "open_hoy": None,
        "close_ayer": None,
        "fuente": ""
    }
    # USD/MXN
    try:
        usd = yf.Ticker("USDMXN=X")
        hd = usd.history(period="5d", interval="1d")
        if len(hd)>=2:
            prev = float(hd['Close'].iloc[-2]); last = float(hd['Close'].iloc[-1])
            estado["usd_pct"] = (last-prev)/prev*100
        # intenta 5m fresco
        hi = usd.history(period="1d", interval="5m")
        if len(hi)>=2:
            estado["usd_pct"] = (float(hi['Close'].iloc[-1]) - float(hi['Close'].iloc[0]))/float(hi['Close'].iloc[0])*100
            estado["fuente"] += "USD 5m; "
    except Exception as e:
        print("USD err", e)

    # IPC ^MXX FIX
    try:
        ipc = yf.Ticker("^MXX")
        hd = ipc.history(period="5d", interval="1d")
        print(f"HD IPC {hd.tail(2)}")
        if len(hd)>=2:
            # Detectar si daily ya trae hoy
            last_date = hd.index[-1].date()
            prev_close = float(hd['Close'].iloc[-2])
            last_close = float(hd['Close'].iloc[-1])
            last_open = float(hd['Open'].iloc[-1])

            if last_date == now.date() and last_open != 0:
                # MERCADO YA ABRIO Y YAHOO TIENE OPEN HOY
                estado["ipc_pct"] = (last_open - prev_close)/prev_close*100
                estado["ipc_tipo"] = "open_hoy_daily"
                estado["open_hoy"] = last_open
                estado["close_ayer"] = prev_close
                estado["fuente"] += f"IPC open_hoy {last_open:.2f} vs close_ayer {prev_close:.2f}; "
            else:
                # No tiene daily de hoy, usa intradia 1m
                hi = ipc.history(period="1d", interval="1m")
                if len(hi)>0:
                    open_intra = float(hi['Open'].iloc[0])
                    # close_ayer es el ultimo close diario disponible
                    close_ayer_real = float(hd['Close'].iloc[-1])
                    estado["ipc_pct"] = (open_intra - close_ayer_real)/close_ayer_real*100
                    estado["ipc_tipo"] = "open_hoy_intraday"
                    estado["open_hoy"] = open_intra
                    estado["close_ayer"] = close_ayer_real
                    estado["fuente"] += f"IPC intraday open {open_intra:.2f} vs close_ayer {close_ayer_real:.2f}; "
                else:
                    # Fallback viejo
                    estado["ipc_pct"] = (last_close - prev_close)/prev_close*100
                    estado["ipc_tipo"] = "cierre_ayer"
                    estado["close_ayer"] = last_close
                    estado["fuente"] += "IPC fallback cierre_ayer; "
    except Exception as e:
        print("IPC err", e)
        estado["ipc_tipo"] = "error"

    # Evaluar nivel
    usd = estado["usd_pct"]; ipc = estado["ipc_pct"]
    if ipc <= -0.76:
        estado["nivel"] = "EXTREMO"
        estado["bloqueo"] = True
        estado["msg"] = f"🚫 IPC {ipc:.2f}% muy rojo - HOY NO OPERES."
    elif ipc <= -0.40:
        estado["nivel"] = "ALTO"
        estado["msg"] = f"⚠️ IPC {ipc:.2f}% rojo"
    elif usd >= 0.8:
        estado["nivel"] = "EXTREMO"; estado["bloqueo"] = True
        estado["msg"] += f" USD/MXN +{usd:.2f}% EXTREMO."
    elif usd >= 0.58:
        if estado["nivel"] == "NORMAL": estado["nivel"] = "ALTO"
        estado["msg"] += f" USD/MXN +{usd:.2f}% alto."

    if usd >= 0.5 and ipc <= -0.3:
        estado["nivel"] = "EXTREMO"; estado["bloqueo"] = True
        estado["msg"] += " 💥 Combo USD↑ + IPC↓."

    if not estado["msg"]:
        estado["msg"] = f"Día normal USD {usd:.2f}% IPC {ipc:.2f}%"

    print(f"MACRO v11: {estado}")
    return estado

def evaluar_un_ticker(base, macro):
    yahoo = MAP_YAHOO[base]
    try:
        tk = yf.Ticker(yahoo)
        h = tk.history(period="3mo", interval="1d")
        if len(h) < 35:
            return {"ticker": yahoo, "bloqueado": f"Sin historial {len(h)}"}
        close = h['Close']
        vol = h['Volume']
        price = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        open_hoy = float(h['Open'].iloc[-1])
        gap = (open_hoy - prev)/prev*100
        vol_mean = float(vol.rolling(20).mean().iloc[-1])
        vol_ratio = float(vol.iloc[-1]/vol_mean) if vol_mean>0 else 1.0
        rsi_v = float(rsi(close).iloc[-1])

        # Filtros duros v10/v11
        if rsi_v > 78:
            return {"ticker": yahoo, "bloqueado": f"RSI {rsi_v:.0f} sobrecompra"}
        if rsi_v < 22:
            return {"ticker": yahoo, "bloqueado": f"RSI {rsi_v:.0f} sobreventa"}
        if vol_ratio < 0.6:
            return {"ticker": yahoo, "bloqueado": f"Vol {vol_ratio:.1f}x bajo"}
        if abs(gap) > 5:
            return {"ticker": yahoo, "bloqueado": f"Gap {gap:.1f}%"}

        # Prob base (calibrada)
        prob_base = 40.9
        prob_base += (rsi_v-50)*-0.18
        prob_base += (vol_ratio-1)*6
        ret5 = (close.iloc[-1]/close.iloc[-6]-1)*100
        prob_base += np.clip(ret5*0.4, -4,4)
        prob_base = float(np.clip(prob_base, 36, 68))

        prob = prob_base
        # Macro ajuste
        if macro["usd_pct"] >= 0.7: prob -= 7
        if macro["usd_pct"] >= 0.8: prob -= 5
        if macro["usd_pct"] <= -0.7: prob += 4
        if macro["ipc_pct"] <= -0.40: prob -= 6
        if macro["ipc_pct"] <= -0.76: prob -= 10

        # Noticias
        score, txt = get_news(base)
        if score==2: prob += 3
        if score==-2: prob -= 6

        prob = float(np.clip(prob, 28, 70))

        return {
            "ticker": yahoo, "base": base, "price": price,
            "venta": price*1.012, "stop": price*0.992,
            "rsi": rsi_v, "vol": vol_ratio, "gap": gap,
            "prob_base": prob_base, "prob": prob,
            "news": txt, "bloqueado": None
        }
    except Exception as e:
        return {"ticker": yahoo, "bloqueado": f"Error {str(e)[:50]}"}

def send_telegram_msg(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Falta TOKEN/CHAT_ID")
        print(text[:2000])
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=15)
        print(f"Telegram {r.status_code}")
    except Exception as e:
        print(f"Telegram error {e}")

def construir_mensaje(resultados, bloqueados, macro):
    hoy = datetime.now(pytz.timezone('America/Mexico_City')).strftime('%Y-%m-%d')
    txt = f"📊 <b>TOP BMV HOY {hoy} v11 - FILTRO IPC OPEN FIX</b>\n"
    txt += f"Tasa base: 40.9% | Evaluadas: {len(resultados)+len(bloqueados)}/40 | Comprables: {len(resultados)}\n"
    txt += f"Macro: {macro['nivel']} | {macro['msg']}\n"
    txt += f"USD/MXN: {macro['usd_pct']:.2f}% | IPC: {macro['ipc_pct']:.2f}% ({macro['ipc_tipo']})\n"
    if macro['fuente']: txt += f"Fuente: {macro['fuente']}\n"
    txt += "\n"
    if macro['bloqueo']:
        txt += f"🚫 <b>HOY NO OPERES - MERCADO EN ROJO</b>\nMotivo: {macro['msg']}\nSi operas hoy, probabilidad real cae a &lt;35%. Mejor esperar mañana.\n\n"

    top = sorted([r for r in resultados if not r.get('bloqueado')], key=lambda x: x['prob'], reverse=True)[:10]
    if top:
        txt += f"<b>TOP 10 COMPRABLES HOY:</b>\n"
        for i,r in enumerate(top,1):
            icono = "👀"
            if r['prob']>=60: icono="✅"
            elif r['prob']>=55: icono="👀"
            link = get_google_link(r['ticker'])
            txt += f"{i}. {icono} <a href='{link}'><b>{r['ticker']}</b></a> {r['prob']:.1f}% (base {r['prob_base']:.1f}%) | ${r['price']:.2f} | Venta ${r['venta']:.2f} | Stop ${r['stop']:.2f} | RSI {r['rsi']:.0f} Vol {r['vol']:.1f}x\n"
            if r['news']:
                txt += f"   📰 [RSS {r['base']}] {r['news'][:110]}\n\n"
    else:
        txt += "Sin oportunidades comprables hoy.\n"
        if bloqueados:
            txt += f"Top bloqueados: {', '.join([b['ticker'][:12]+' '+b['bloqueado'] for b in bloqueados[:3]])}\n\n"

    txt += "🔗 Click en ticker abre Google Finance\n⚠️ Hey sin stop auto. Alerta TradingView en Stop.\n\nComandos: /top /ahora /macro /ayuda"
    return txt[:4000]

def main_job():
    try:
        macro = get_macro_state_v11()
        resultados = []; bloqueados = []
        for base in TICKERS_BMV:
            res = evaluar_un_ticker(base, macro)
            if res is None: continue
            if res.get('bloqueado'):
                bloqueados.append(res)
            else:
                resultados.append(res)
        msg = construir_mensaje(resultados, bloqueados, macro)
        send_telegram_msg(msg)
    except Exception as e:
        import traceback
        err = traceback.format_exc()[-1500:]
        send_telegram_msg(f"❌ Bot v11 fallo {e}\n{err}")

if __name__ == "__main__":
    main_job()
