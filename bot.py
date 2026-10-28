
import os, yfinance as yf, pandas as pd, numpy as np, requests, datetime, xml.etree.ElementTree as ET, traceback
from xgboost import XGBClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
import warnings; warnings.filterwarnings('ignore')

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
  
def send_telegram(text):
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id":CHAT_ID,"text":text,"parse_mode":"Markdown"}, timeout=15)
        except Exception as e:
            print(f"Error telegram: {e}")
    print(text)

try:
    DIAS_BANXICO = ["2026-02-05","2026-03-26","2026-05-14","2026-06-25","2026-08-06","2026-09-24","2026-11-05","2026-12-17"]
    NEGATIVAS = ["demanda","fraude","pérdida","perdida","baja","recorte","caída","caida","investigación","multa","quiebra","huelga","demora","falla","escándalo","lawsuit","fraud","loss","downgrade","cut","miss"]
    POSITIVAS = ["récord","record","alza","sube","ganancia","crecimiento","expansión","contrato","aprobación","incremento","utilidad","beat","upgrade","growth","gain","surge","profit","win"]

    def get_macro_state():
        estado = {"riesgo":"BAJO","usdmxn_chg":0,"mxx_chg":0,"es_banxico":False,"mensaje":""}
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
                estado["mensaje"]+= "📢 HOY BANXICO 13:00. "
            if estado["usdmxn_chg"]>=1.2:
                estado["riesgo"]="EXTREMO"; estado["mensaje"]+= f"💥 USD/MXN +{estado['usdmxn_chg']}% "
            elif estado["usdmxn_chg"]>=0.7:
                estado["riesgo"]="ALTO"; estado["mensaje"]+= f"⚠️ USD/MXN +{estado['usdmxn_chg']}% "
            elif estado["usdmxn_chg"]<=-0.7:
                estado["riesgo"]="FAVORABLE"; estado["mensaje"]+= f"✅ USD/MXN {estado['usdmxn_chg']}% "
            if estado["mxx_chg"]<=-1.0:
                estado["riesgo"]="ALTO" if estado["riesgo"]!="EXTREMO" else "EXTREMO"
                estado["mensaje"]+= f"📉 IPC {estado['mxx_chg']}% "
            if not estado["mensaje"]:
                estado["mensaje"]=f"Día normal USD {estado['usdmxn_chg']}% IPC {estado['mxx_chg']}%"
        except Exception as e:
            estado["mensaje"]=f"Macro error {e}"
        return estado

    def get_base_ticker(ticker_mx):
        t = ticker_mx.replace(".MX","")
        mapa = {"GAPB":"GAP","CEMEXCPO":"CEMEX","GCARSOA1":"GCARSO","TLEVISACPO":"TLEVISA","PINFRA":"PINFRA","PEOLES":"PEOLES","SORIANAB":"SORIANA","FIBRAMQ12":"FIBRAMQ","FMTY14":"FMTY","KOFUBL":"KOF","BIMBOA":"BIMBO","GRUMAB":"GRUMA","KIMBERA":"KIMBER","HERDEZ":"HERDEZ","CUERVO":"CUERVO","NAFTRACISHRS":"NAFTRAC","IVVPESOISHRS":"IVV","VOLARA":"VOLAR"}
        for k,v in mapa.items():
            if k in t: return v
        return t[:6]

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
        candidatos = [ticker_mx.replace(".MX",""), get_base_ticker(ticker_mx)]
        for cand in dict.fromkeys(candidatos):
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
        base = get_base_ticker(ticker_mx)
        titulos = fetch_google_rss(f"{base} acciones")
        if titulos:
            txt = " | ".join(titulos)[:170]
            tl = txt.lower()
            score = sum(1 for w in POSITIVAS if w in tl) - sum(1 for w in NEGATIVAS if w in tl)
            sent = 0
            if score<=-2: sent=-1
            elif score==-1: sent=-0.5
            elif score>=2: sent=1
            elif score==1: sent=0.5
            return sent, f"[RSS {base}] {txt}"
        return 0, ""

    # LISTA 40 SIN CARACTERES RAROS - PE&OLES -> PEOLES.MX
    tickers = [
        "AAPL.MX","AC.MX","AMXB.MX","AMZN.MX","BBVA.MX","BIMBOA.MX","CEMEXCPO.MX","CUERVO.MX","F.MX","FIBRAMQ12.MX",
        "FMTY14.MX","GAPB.MX","GCARSOA1.MX","GFINBURO.MX","GFNORTEO.MX","GMEXICOB.MX","GOOGL.MX","GRUMAB.MX","HERDEZ.MX",
        "IEO.MX","INTC.MX","IVVPESOISHRS.MX","KIMBERA.MX","KOFUBL.MX","META.MX","MSFT.MX","NAFTRACISHRS.MX","NEMAKA.MX",
        "NFLX.MX","NOKN.MX","NVDA.MX","PEOLES.MX","PINFRA.MX","SLV.MX","SORIANAB.MX","TLEVISACPO.MX","TM.MX","TSLA.MX","VOLARA.MX","WALMEX.MX"
    ]

    def rsi(s,p=14):
        delta=s.diff(); gain=delta.where(delta>0,0).rolling(p).mean(); loss=-delta.where(delta<0,0).rolling(p).mean(); rs=gain/loss; return 100-(100/(1+rs))

    all_data={}
    for t in tickers:
        try:
            df=yf.Ticker(t).history(period="2y", auto_adjust=True)
            if len(df)>100: all_data[t]=df
        except: pass

    if not all_data:
        raise Exception("No se pudo descargar ningún ticker de Yahoo. Yahoo bloqueado hoy.")

    rows=[]
    for t,df in all_data.items():
        d=df.copy()
        d['Ret_1d']=d['Close'].pct_change(1); d['Ret_5d']=d['Close'].pct_change(5)
        d['Gap']=(d['Open']-d['Close'].shift(1))/d['Close'].shift(1)
        d['Vol_MA20']=d['Volume'].rolling(20).mean(); d['Vol_Ratio']=d['Volume']/d['Vol_MA20']
        d['Dist_MA20']=(d['Close']-d['Close'].rolling(20).mean())/d['Close'].rolling(20).mean()
        d['RSI']=rsi(d['Close']); d['Target']=(d['High']>=d['Open']*1.012).astype(int)
        d.dropna(inplace=True); d['Ticker']=t; rows.append(d)

    master=pd.concat(rows)
    features=['Ret_1d','Ret_5d','Gap','Vol_Ratio','Dist_MA20','RSI']
    X=master[features]; y=master['Target']
    base_model=XGBClassifier(n_estimators=150,max_depth=2,learning_rate=0.03,min_child_weight=10,reg_alpha=1,reg_lambda=2,subsample=0.7,colsample_bytree=0.7,random_state=42,eval_metric='logloss')
    calibrated=CalibratedClassifierCV(base_model, method='sigmoid', cv=TimeSeriesSplit(3))
    calibrated.fit(X,y)
    proba_raw=calibrated.predict_proba(X)[:,1]
    p10,p90=np.percentile(proba_raw,[10,90])
    macro = get_macro_state()

    resultados=[]
    for t,df in all_data.items():
        d=df.copy()
        d['Ret_1d']=d['Close'].pct_change(1); d['Ret_5d']=d['Close'].pct_change(5)
        d['Gap']=(d['Open']-d['Close'].shift(1))/d['Close'].shift(1)
        d['Vol_MA20']=d['Volume'].rolling(20).mean(); d['Vol_Ratio']=d['Volume']/d['Vol_MA20']
        d['Dist_MA20']=(d['Close']-d['Close'].rolling(20).mean())/d['Close'].rolling(20).mean()
        d['RSI']=rsi(d['Close']); d=d.dropna()
        if d.empty: continue
        last=d.iloc[-1]
        raw=calibrated.predict_proba([[last['Ret_1d'],last['Ret_5d'],last['Gap'],last['Vol_Ratio'],last['Dist_MA20'],last['RSI']]])[0,1]
        prob=52 + (np.clip(raw,p10,p90)-p10)/(p90-p10+1e-9)*16
        sent, noticia = analizar_noticia(t)
        comprable=True; prob_aj=prob
        if last['RSI']>75: comprable=False
        elif sent==-1: comprable=False; prob_aj-=10
        elif sent==-0.5: prob_aj-=5
        elif sent==1: prob_aj+=3
        if macro["riesgo"]=="EXTREMO": comprable=False; prob_aj-=15
        elif macro["riesgo"]=="ALTO": prob_aj-=7
        elif macro["riesgo"]=="FAVORABLE": prob_aj+=4
        if comprable:
            resultados.append({'Ticker':t,'Prob':prob,'Prob_Ajustada':max(45,min(75,prob_aj)),'Close':last['Close'],'RSI':last['RSI'],'Noticia':noticia})

    resultados=sorted(resultados,key=lambda x: x['Prob_Ajustada'],reverse=True)
    hoy_str = pd.Timestamp.now().date()
    msg = f"📊 *TOP BMV HOY {hoy_str} v8.2*\n"
    msg += f"Tasa base: {master['Target'].mean()*100:.1f}% | Evaluadas: {len(all_data)}/40\n"
    msg += f"Macro: {macro['riesgo']} | {macro['mensaje']}\n"
    msg += f"USD/MXN: {macro['usdmxn_chg']}% | IPC: {macro['mxx_chg']}%\n\n"

    if macro["riesgo"]=="EXTREMO":
        msg += f"🚫 *HOY NO OPERES*\n"
    else:
        top = [r for r in resultados if r['Prob_Ajustada']>=58][:5]
        if top:
            for r in top:
                msg += f"*{r['Ticker']}* {r['Prob_Ajustada']:.1f}% (base {r['Prob']:.1f}%) | ${r['Close']:.2f} | Venta ${r['Close']*1.012:.2f} | Stop ${r['Close']*0.992:.2f} | RSI {r['RSI']:.0f}\n"
                if r['Noticia']:
                    msg += f"  📰 {r['Noticia'][:110]}\n"
                msg += "\n"
        else:
            msg += "Sin oportunidades >58%. No operes hoy.\n"
            for r in resultados[:3]:
                msg += f"  {r['Ticker']} {r['Prob_Ajustada']:.1f}%\n"
    msg += "\n⚠️ Hey sin stop auto. Alerta TradingView."
    send_telegram(msg)

except Exception as e:
    err = traceback.format_exc()[-1500:]
    msg_err = f"❌ *BOT FALLÓ HOY {datetime.date.today()}*\nError: {str(e)[:300]}\n\nLog:\n{err}\n\nRevisa Secrets TELEGRAM_TOKEN y CHAT_ID"
    send_telegram(msg_err)
