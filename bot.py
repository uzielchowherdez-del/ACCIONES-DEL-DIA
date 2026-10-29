
import os, yfinance as yf, pandas as pd, numpy as np, requests, datetime, xml.etree.ElementTree as ET, traceback, time
from xgboost import XGBClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
import warnings; warnings.filterwarnings('ignore')

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(text, parse_mode="HTML"):
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}, timeout=20)
        except Exception as e:
            print(f"Error telegram: {e}")
    print(text)

def get_google_finance_link(ticker_mx):
    base = ticker_mx.replace(".MX","").replace("ISHRS","")
    return f"https://www.google.com/finance/quote/{base}:BMV", base

DIAS_BANXICO = ["2026-02-05","2026-03-26","2026-05-14","2026-06-25","2026-08-06","2026-09-24","2026-11-05","2026-12-17"]
NEGATIVAS = ["demanda","fraude","pérdida","perdida","baja","recorte","caída","caida","investigación","multa","quiebra","huelga","demora","falla","escándalo","lawsuit","fraud","loss","downgrade","cut","miss"]
POSITIVAS = ["récord","record","alza","sube","ganancia","crecimiento","expansión","contrato","aprobación","incremento","utilidad","beat","upgrade","growth","gain","surge","profit","win"]

def get_macro_state():
    estado = {"riesgo":"BAJO","usdmxn_chg":0,"mxx_chg":0,"es_banxico":False,"mensaje":"","bloqueo":False}
    try:
        usd = yf.Ticker("USDMXN=X").history(period="5d")
        if len(usd)>=2:
            estado["usdmxn_chg"] = round(float((usd['Close'].iloc[-1]-usd['Close'].iloc[-2])/usd['Close'].iloc[-2]*100),2)
        mxx = yf.Ticker("^MXX").history(period="5d")
        if len(mxx)>=2:
            estado["mxx_chg"] = round(float((mxx['Close'].iloc[-1]-mxx['Close'].iloc[-2])/mxx['Close'].iloc[-2]*100),2)
        hoy = datetime.date.today().isoformat()
        if hoy in DIAS_BANXICO:
            estado["es_banxico"]=True
            estado["mensaje"]+= "📢 HOY BANXICO 13:00 - Cierra antes 12:50. "

        # --- NUEVO FILTRO v10 IPC ---
        if estado["mxx_chg"] <= -0.4:
            estado["riesgo"]="EXTREMO"
            estado["bloqueo"]=True
            estado["mensaje"]+= f"🚫 IPC {estado['mxx_chg']}% muy rojo - HOY NO OPERES. "
        elif estado["mxx_chg"] <= -0.25:
            estado["riesgo"]="ALTO"
            estado["mensaje"]+= f"⚠️ IPC {estado['mxx_chg']}% negativo. "

        if estado["usdmxn_chg"]>=1.2:
            estado["riesgo"]="EXTREMO"; estado["bloqueo"]=True; estado["mensaje"]+= f"💥 USD/MXN +{estado['usdmxn_chg']}% EXTREMO. "
        elif estado["usdmxn_chg"]>=0.7:
            if estado["riesgo"]!="EXTREMO":
                estado["riesgo"]="ALTO"
            estado["mensaje"]+= f"⚠️ USD/MXN +{estado['usdmxn_chg']}% ALTO. "
        elif estado["usdmxn_chg"]<=-0.7:
            if estado["riesgo"]=="BAJO":
                estado["riesgo"]="FAVORABLE"
            estado["mensaje"]+= f"✅ USD/MXN {estado['usdmxn_chg']}% favorable. "

        # Combo mortal: USD arriba + IPC abajo
        if estado["usdmxn_chg"]>=0.5 and estado["mxx_chg"]<=-0.3:
            estado["riesgo"]="EXTREMO"; estado["bloqueo"]=True
            estado["mensaje"]+= f"💥 Combo USD↑ + IPC↓. "

        if not estado["mensaje"]:
            estado["mensaje"]=f"Día normal USD {estado['usdmxn_chg']}% IPC {estado['mxx_chg']}%"
    except Exception as e:
        estado["mensaje"]=f"Macro error {e}"
    return estado

def fetch_yahoo_news(cand):
    try:
        news = yf.Ticker(cand).news
        if not news: return []
        titulos=[]
        for n in news[:2]:
            title=""
            if isinstance(n, dict):
                title = n.get('title') or (n.get('content',{}).get('title','') if isinstance(n.get('content'), dict) else "")
            if title: titulos.append(title)
        return titulos
    except:
        return []

def fetch_google_rss(query):
    try:
        q = query.replace(" ","+")
        url = f"https://news.google.com/rss/search?q={q}+Mexico&hl=es-419&gl=MX&ceid=MX:es-419"
        r = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        root = ET.fromstring(r.content)
        titulos=[]
        for item in root.findall(".//item")[:2]:
            t = item.find("title")
            if t is not None and t.text:
                titulos.append(t.text[:120])
        return titulos
    except:
        return []

def analizar_noticia(ticker_mx):
    base_simple = ticker_mx.replace(".MX","").replace("ISHRS","")
    for cand in dict.fromkeys([ticker_mx.replace(".MX",""), base_simple]):
        titulos = fetch_yahoo_news(cand)
        if titulos:
            txt = " | ".join(titulos)[:170]
            tl = txt.lower()
            score = sum(1 for w in POSITIVAS if w in tl) - sum(1 for w in NEGATIVAS if w in tl)
            sent = 0
            if score<=-2: sent=-1
            elif score==-1: sent=-0.5
            elif score>=2: sent=1
            elif score==1: sent=0.5
            return sent, f"[{cand}] {txt}"
    titulos = fetch_google_rss(f"{base_simple} acciones")
    if titulos:
        txt = " | ".join(titulos)[:170]
        tl = txt.lower()
        score = sum(1 for w in POSITIVAS if w in tl) - sum(1 for w in NEGATIVAS if w in tl)
        sent = 0
        if score<=-2: sent=-1
        elif score==-1: sent=-0.5
        elif score>=2: sent=1
        elif score==1: sent=0.5
        return sent, f"[RSS {base_simple}] {txt}"
    return 0, ""

def rsi_calc(s,p=14):
    delta=s.diff(); gain=delta.where(delta>0,0).rolling(p).mean(); loss=-delta.where(delta<0,0).rolling(p).mean(); rs=gain/loss; return 100-(100/(1+rs))

def generar_top():
    tickers = [
        "AAPL.MX","AC.MX","AMXB.MX","AMZN.MX","BBVA.MX","BIMBOA.MX","CEMEXCPO.MX","CUERVO.MX","F.MX","FIBRAMQ12.MX",
        "FMTY14.MX","GAPB.MX","GCARSOA1.MX","GFINBURO.MX","GFNORTEO.MX","GMEXICOB.MX","GOOGL.MX","GRUMAB.MX","HERDEZ.MX",
        "IEO.MX","INTC.MX","IVVPESOISHRS.MX","KIMBERA.MX","KOFUBL.MX","META.MX","MSFT.MX","NAFTRACISHRS.MX","NEMAKA.MX",
        "NFLX.MX","NOKN.MX","NVDA.MX","PEOLES.MX","PINFRA.MX","SLV.MX","SORIANAB.MX","TLEVISACPO.MX","TM.MX","TSLA.MX","VOLARA.MX","WALMEX.MX"
    ]
    all_data={}
    for t in tickers:
        try:
            df=yf.Ticker(t).history(period="2y", auto_adjust=True)
            if len(df)>100: all_data[t]=df
        except: pass
    if not all_data:
        raise Exception("Yahoo bloqueado - no data")
    rows=[]
    for t,df in all_data.items():
        d=df.copy()
        d['Ret_1d']=d['Close'].pct_change(1); d['Ret_5d']=d['Close'].pct_change(5)
        d['Gap']=(d['Open']-d['Close'].shift(1))/d['Close'].shift(1)
        d['Vol_MA20']=d['Volume'].rolling(20).mean(); d['Vol_Ratio']=d['Volume']/d['Vol_MA20']
        d['Dist_MA20']=(d['Close']-d['Close'].rolling(20).mean())/d['Close'].rolling(20).mean()
        d['RSI']=rsi_calc(d['Close']); d['Target']=(d['High']>=d['Open']*1.012).astype(int)
        d.dropna(inplace=True); d['Ticker']=t; rows.append(d)
    master=pd.concat(rows)
    features=['Ret_1d','Ret_5d','Gap','Vol_Ratio','Dist_MA20','RSI']
    X=master[features]; y=master['Target']
    base_model=XGBClassifier(n_estimators=200,max_depth=2,learning_rate=0.03,min_child_weight=10,reg_alpha=1,reg_lambda=2,subsample=0.7,colsample_bytree=0.7,random_state=42,eval_metric='logloss')
    calibrated=CalibratedClassifierCV(base_model, method='sigmoid', cv=TimeSeriesSplit(3))
    calibrated.fit(X,y)
    proba_raw=calibrated.predict_proba(X)[:,1]
    p10,p90=np.percentile(proba_raw,[10,90])
    macro = get_macro_state()
    resultados=[]
    bloqueados=[]
    for t,df in all_data.items():
        d=df.copy()
        d['Ret_1d']=d['Close'].pct_change(1); d['Ret_5d']=d['Close'].pct_change(5)
        d['Gap']=(d['Open']-d['Close'].shift(1))/d['Close'].shift(1)
        d['Vol_MA20']=d['Volume'].rolling(20).mean(); d['Vol_Ratio']=d['Volume']/d['Vol_MA20']
        d['Dist_MA20']=(d['Close']-d['Close'].rolling(20).mean())/d['Close'].rolling(20).mean()
        d['RSI']=rsi_calc(d['Close']); d=d.dropna()
        if d.empty: continue
        last=d.iloc[-1]
        raw=calibrated.predict_proba([[last['Ret_1d'],last['Ret_5d'],last['Gap'],last['Vol_Ratio'],last['Dist_MA20'],last['RSI']]])[0,1]
        prob=52 + (np.clip(raw,p10,p90)-p10)/(p90-p10+1e-9)*16
        sent, noticia = analizar_noticia(t)
        prob_aj=prob
        motivo=[]
        bloqueado=False
        # FILTROS v10
        if last['RSI']>78:
            bloqueado=True; motivo.append(f"RSI {last['RSI']:.0f} sobrecompra")
        elif last['RSI']<22:
            bloqueado=True; motivo.append(f"RSI {last['RSI']:.0f} sobreventa")
        if last['Vol_Ratio']<0.6:
            bloqueado=True; motivo.append(f"Sin volumen {last['Vol_Ratio']:.1f}x")
        if abs(last['Gap'])>0.05:
            bloqueado=True; motivo.append(f"Gap {last['Gap']*100:.1f}%")
        if sent==-1:
            bloqueado=True; motivo.append(f"Noticia negativa"); prob_aj-=10
        elif sent==-0.5:
            prob_aj-=5
        elif sent==1:
            prob_aj+=3
        if macro["riesgo"]=="EXTREMO":
            prob_aj-=15
        elif macro["riesgo"]=="ALTO":
            prob_aj-=7
        elif macro["riesgo"]=="FAVORABLE":
            prob_aj+=4
        gf_link, gf_base = get_google_finance_link(t)
        item={'Ticker':t,'Prob':prob,'Prob_Ajustada':max(45,min(78,prob_aj)),'Close':last['Close'],'RSI':last['RSI'],'Noticia':noticia,'GF_Link':gf_link,'GF_Base':gf_base,'Motivo':", ".join(motivo),'Bloqueado':bloqueado,'Vol_Ratio':last['Vol_Ratio'],'Gap':last['Gap']}
        if bloqueado:
            bloqueados.append(item)
        else:
            resultados.append(item)
    resultados=sorted(resultados,key=lambda x: x['Prob_Ajustada'],reverse=True)
    bloqueados=sorted(bloqueados,key=lambda x: x['Prob_Ajustada'],reverse=True)
    return resultados, bloqueados, macro, master

def construir_mensaje(resultados, bloqueados, macro, master):
    hoy_str = pd.Timestamp.now().date()
    msg = f"📊 <b>TOP BMV HOY {hoy_str} v10 - FILTRO IPC</b>\n"
    msg += f"Tasa base: {master['Target'].mean()*100:.1f}% | Evaluadas: {len(resultados)+len(bloqueados)}/40 | Comprables: {len(resultados)}\n"
    msg += f"Macro: {macro['riesgo']} | {macro['mensaje']}\n"
    msg += f"USD/MXN: {macro['usdmxn_chg']}% | IPC: {macro['mxx_chg']}%\n\n"
    if macro["bloqueo"]:
        msg += f"🚫 <b>HOY NO OPERES - MERCADO EN ROJO</b>\n"
        msg += f"Motivo: {macro['mensaje']}\n"
        msg += f"Si operas hoy, probabilidad real cae a &lt;35%. Mejor esperar mañana.\n\n"
    # TOP 10 comprables
    top10 = resultados[:10]
    if top10:
        msg += f"<b>TOP 10 COMPRABLES HOY:</b>\n"
        for i,r in enumerate(top10,1):
            icono = "✅" if r['Prob_Ajustada']>=60 else "⚠️" if r['Prob_Ajustada']>=58 else "👀"
            msg += f"{i}. {icono} <a href='{r['GF_Link']}'><b>{r['Ticker']}</b></a> {r['Prob_Ajustada']:.1f}% (base {r['Prob']:.1f}%) | ${r['Close']:.2f} | Venta ${r['Close']*1.012:.2f} | Stop ${r['Close']*0.992:.2f} | RSI {r['RSI']:.0f} Vol {r['Vol_Ratio']:.1f}x\n"
            if r['Noticia']:
                msg += f"   📰 {r['Noticia'][:110]}\n"
            msg += "\n"
    else:
        msg += "Sin oportunidades comprables hoy. No operes.\n\n"
        if bloqueados:
            msg += f"<b>Top bloqueados por filtros v10 (para referencia):</b>\n"
            for r in bloqueados[:3]:
                msg += f"  {r['Ticker']} {r['Prob_Ajustada']:.1f}% - {r['Motivo']}\n"
            msg += "\n"
    msg += "🔗 Click en ticker abre Google Finance\n"
    msg += "⚠️ Hey sin stop auto. Alerta TradingView en Stop.\n"
    msg += "\nComandos: /top /ahora /macro /ayuda"
    return msg

try:
    resultados, bloqueados, macro, master = generar_top()
    mensaje = construir_mensaje(resultados, bloqueados, macro, master)
    send_telegram(mensaje)
except Exception as e:
    err = traceback.format_exc()[-1200:]
    send_telegram(f"❌ <b>BOT v10 FALLÓ {datetime.date.today()}</b>\n{str(e)[:400]}\n{err}")

if len(os.sys.argv)>1 and os.sys.argv[1]=="interactive":
    print("Modo interactivo v10 activo...")
    last_update_id = 0
    while True:
        try:
            resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id+1}&timeout=20", timeout=25).json()
            for upd in resp.get("result",[]):
                last_update_id = upd["update_id"]
                msg_obj = upd.get("message",{})
                chat_id = str(msg_obj.get("chat",{}).get("id",""))
                text = msg_obj.get("text","").lower().strip()
                if chat_id != str(CHAT_ID): continue
                if text in ["/top","/ahora","/top10","ahora","top"]:
                    send_telegram("⏳ Calculando TOP 10 v10 con filtro IPC...")
                    res, bloq, mac, mast = generar_top()
                    send_telegram(construir_mensaje(res, bloq, mac, mast))
                elif text in ["/macro","/usd","macro"]:
                    mac = get_macro_state()
                    send_telegram(f"📈 <b>Macro ahora v10</b>\nRiesgo: {mac['riesgo']}\n{mac['mensaje']}\nUSD/MXN: {mac['usdmxn_chg']}% | IPC: {mac['mxx_chg']}%\nBloqueo: {mac['bloqueo']}")
                elif text in ["/ayuda","/help","/start","ayuda","help"]:
                    send_telegram("🤖 <b>Comandos BMV v10</b>\n/top o /ahora - TOP 10 con filtro IPC\n/macro - Estado USD/MXN e IPC\n/ayuda - Esta ayuda\n\nNuevo en v10: Si IPC < -0.4% bloquea todo.")
        except Exception as e:
            print(f"Loop error {e}")
            time.sleep(5)
