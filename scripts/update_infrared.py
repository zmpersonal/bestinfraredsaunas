#!/usr/bin/env python3
from pathlib import Path
import requests, json, csv, re, html, statistics, sys, shutil
from bs4 import BeautifulSoup
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
BASE='https://inhousewellness.com'
COLLECTION=f'{BASE}/collections/infrared-saunas'
DOMAIN='https://besthomeinfraredsauna.com'
UA={'User-Agent':'Mozilla/5.0 (compatible; BestHomeInfraredSaunaBot/2.0; +https://besthomeinfraredsauna.com/methodology/)'}
NEGATIVE=('traditional','hybrid','steam sauna','wood-burning','wood burning')
INFRARED=('infrared','far ir','far infrared','full spectrum','nir ','near infrared')

RETAILERS={
 'inhouse-wellness': {
   'slug':'inhouse-wellness','name':'InHouse Wellness','outbound_url':'https://inhousewellness.com/collections/infrared-saunas',
   'description':'Our featured retailer for infrared models it currently carries. The model index remains independent of retailer status.'
 }
}

def get_json(url):
    r=requests.get(url,headers=UA,timeout=35); r.raise_for_status(); return r.json()
def get_text(url):
    r=requests.get(url,headers=UA,timeout=35); r.raise_for_status(); return r.text

def clean(txt): return re.sub(r'\s+',' ',txt or '').strip()
def slugify(s): return (re.sub(r'[^a-z0-9]+','-',(s or '').lower()).strip('-')[:90] or 'infrared-sauna')
def money(x): return f'${x:,.0f}' if isinstance(x,(int,float)) else '—'
def val(x,s=''):
    if x in (None,''): return '—'
    if isinstance(x,float): return f'{x:g}{s}'
    return f'{x}{s}'

def pure_infrared(p):
    title=clean(p.get('title','')).lower(); product_type=clean(p.get('product_type','')).lower()
    tags=p.get('tags',[]); tags=[tags] if isinstance(tags,str) else tags
    structural=' '.join([title,product_type,' '.join(map(str,tags)).lower()])
    if any(x in structural for x in NEGATIVE): return False
    body=clean(p.get('body_html','')).lower()
    return any(x in (structural+' '+body[:4000]) for x in INFRARED)

def parse_specs(text,title=''):
    t=clean(text); low=t.lower(); out={}
    m=re.search(r'(\d+)\s*(?:-|–)?\s*person',title,re.I) or re.search(r'(\d+)\s*(?:-|–)?\s*person',t,re.I)
    if m: out['capacity']=int(m.group(1))
    patterns=[
      r'Exterior\s+(?:Dimensions?|dimensions?).{0,80}?(\d+(?:\.\d+)?)\s*(?:"|″|in(?:ches)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:"|″|in(?:ches)?)\s*[x×]\s*(\d+(?:\.\d+)?)',
      r'Exterior[^\n]{0,100}?Width\s*[:\-]?\s*(\d+(?:\.\d+)?)[^\n]{0,100}?Depth\s*[:\-]?\s*(\d+(?:\.\d+)?)[^\n]{0,100}?Height\s*[:\-]?\s*(\d+(?:\.\d+)?)',
      r'(?:Exterior\s*)?(\d+(?:\.\d+)?)\s*["″]?\s*[Ww]\s*[x×]\s*(\d+(?:\.\d+)?)\s*["″]?\s*[Dd]\s*[x×]\s*(\d+(?:\.\d+)?)\s*["″]?\s*[Hh]'
    ]
    for p in patterns:
        m=re.search(p,t,re.I)
        if m: out.update(width=float(m.group(1)),depth=float(m.group(2)),height=float(m.group(3))); break
    m=re.search(r'(120|220|240)\s*(?:V|volt)[^\d]{0,30}(\d{1,2}(?:\.\d+)?)\s*(?:A|amp)',t,re.I)
    if not m: m=re.search(r'(120|220|240)\s*V\s*/\s*(\d{1,2}(?:\.\d+)?)\s*A',t,re.I)
    if m: out.update(voltage=int(m.group(1)),amps=float(m.group(2)))
    if re.search(r'two\s+dedicated\s+120',low) or re.search(r'2\s+(?:dedicated\s+)?120',low): out['circuits']=2
    elif out.get('voltage'): out['circuits']=1
    m=re.search(r'(\d{3,5})\s*(?:watts|watt|W\b)',t,re.I)
    if m: out['watts']=int(m.group(1))
    if 'full spectrum' in low or ('near' in low and 'mid' in low and 'far' in low): out['spectrum']='Full Spectrum'
    elif 'far infrared' in low or 'far ir' in low: out['spectrum']='FAR Infrared'
    if 'near zero emf' in low or 'near-zero emf' in low: out['emf_label']='Near Zero EMF'
    elif 'ultra low emf' in low or 'ultra-low emf' in low: out['emf_label']='Ultra Low EMF'
    elif 'low emf' in low or 'low-emf' in low: out['emf_label']='Low EMF'
    mm=re.search(r'((?:under|less than|below|between)?\s*\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s*mG)',t,re.I)
    if mm: out['emf_claim']=clean(mm.group(1))
    dm=re.search(r'(\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s*(?:inches|inch|in|″))\s+(?:from|away)',t,re.I)
    if dm: out['emf_distance']=clean(dm.group(1))+' from heater/panel'
    out['red_light']=('red light' in low or 'red-light' in low)
    if 'canadian hemlock' in low: out['wood']='Canadian Hemlock'
    elif 'mahogany' in low and 'basswood' in low: out['wood']='Mahogany / Basswood'
    elif 'mahogany' in low: out['wood']='Mahogany'
    elif 'eucalyptus' in low: out['wood']='Eucalyptus'
    elif 'cedar' in low and 'aspen' in low: out['wood']='Cedar / Aspen'
    elif 'cedar' in low: out['wood']='Cedar'
    vals=[int(x) for x in re.findall(r'(?:max(?:imum)?(?: temperature)?[^\d]{0,20}|up to\s*)(1[1-9]\d)\s*°?F',t,re.I)]
    if vals: out['max_temp']=max(vals)
    return out

def extract_page_data(page):
    soup=BeautifulSoup(page,'html.parser')
    text=soup.get_text(' ',strip=True)
    image=''
    og=soup.find('meta',attrs={'property':'og:image'}) or soup.find('meta',attrs={'name':'twitter:image'})
    if og: image=og.get('content','')
    price=None
    for tag in soup.find_all('script',type='application/ld+json'):
        try:
            raw=json.loads(tag.string or '{}')
            objs=raw if isinstance(raw,list) else ([raw]+(raw.get('@graph',[]) if isinstance(raw,dict) else []))
            for obj in objs:
                if not isinstance(obj,dict) or obj.get('@type')!='Product': continue
                if not image:
                    im=obj.get('image')
                    if isinstance(im,list) and im: image=im[0] if isinstance(im[0],str) else im[0].get('url','')
                    elif isinstance(im,str): image=im
                    elif isinstance(im,dict): image=im.get('url','')
                offers=obj.get('offers')
                if isinstance(offers,list): offers=offers[0] if offers else None
                if isinstance(offers,dict):
                    try: price=float(offers.get('price')) if offers.get('price') not in (None,'') else price
                    except: pass
        except Exception: pass
    return text,image,price

def first_variant(p):
    vs=p.get('variants') or []; available=[v for v in vs if v.get('available',True)]
    return (available or vs or [{}])[0]

def model_name(title,sku):
    q=re.search(r'["“]([^"”]{2,30})["”]',title)
    if q: return q.group(1)
    if sku: return sku
    x=re.sub(r'\b(?:infrared|sauna|far|emf|low|ultra|near|zero|person|full spectrum|red light|therapy)\b',' ',title,flags=re.I)
    return clean(x)[:45]

def inhouse_products():
    try:
        data=get_json(COLLECTION+'/products.json?limit=250')
        if data.get('products'): return data['products']
    except Exception as e: print('Collection JSON unavailable:',e)
    try:
        page=get_text(COLLECTION)
    except Exception as e:
        print('Collection HTML unavailable:',e)
        return []
    soup=BeautifulSoup(page,'html.parser'); handles=[]
    for a in soup.select('a[href*="/products/"]'):
        href=a.get('href','').split('?')[0]
        if '/products/' in href:
            h=href.split('/products/',1)[1].strip('/')
            if h and h not in handles: handles.append(h)
    out=[]
    for h in handles:
        try:
            p=get_json(f'{BASE}/products/{h}.js'); p['handle']=h; out.append(p)
        except Exception as e: print('Skip',h,e)
    return out

def scrape_inhouse(old):
    results=[]
    for p in inhouse_products():
        if not pure_infrared(p):
            print('Excluded non-infrared:',p.get('title')); continue
        handle=p.get('handle') or slugify(p.get('title')); url=f'{BASE}/products/{handle}'
        page=''; text=BeautifulSoup(p.get('body_html',''),'html.parser').get_text(' ',strip=True); page_image=''; page_price=None
        try:
            page=get_text(url); text,page_image,page_price=extract_page_data(page)
        except Exception as e: print('Page fetch failed',url,e)
        v=first_variant(p); price=v.get('price'); compare=v.get('compare_at_price')
        if isinstance(price,int): price=price/100
        else:
            try: price=float(price) if price not in (None,'') else page_price
            except: price=page_price
        if isinstance(compare,int): compare=compare/100
        else:
            try: compare=float(compare) if compare not in (None,'') else None
            except: compare=None
        sku=clean(v.get('sku','')); title=clean(p.get('title','')); vendor=clean(p.get('vendor','')) or 'Unknown'
        im=''
        if isinstance(p.get('image'),dict): im=p['image'].get('src','')
        if not im and p.get('images'):
            first=p['images'][0]; im=first.get('src','') if isinstance(first,dict) else str(first)
        im=im or page_image
        rec={
          'slug':slugify(sku or handle),'brand':vendor,'model':model_name(title,sku),'sku':sku,'title':title,
          'price':price,'msrp':compare,'capacity':None,'width':None,'depth':None,'height':None,'voltage':None,'amps':None,'circuits':None,'watts':None,
          'spectrum':'Infrared','emf_label':'Not stated','emf_claim':'','emf_distance':'','red_light':False,'wood':'','max_temp':None,'indoor':True,
          'source_url':url,'last_checked':datetime.now(timezone.utc).date().isoformat(),'source':'InHouse Wellness','retailer_slug':'inhouse-wellness',
          'source_group':'featured','source_priority':0,'pure_infrared':True,'traditional':False,'hybrid':False,'image':im
        }
        rec.update(parse_specs(text,title))
        prior=old.get(rec['slug'],{})
        for k in ('capacity','width','depth','height','voltage','amps','circuits','watts','emf_claim','emf_distance','wood','max_temp','sku','image'):
            if rec.get(k) in (None,'','Not stated') and prior.get(k) not in (None,''): rec[k]=prior[k]
        if not rec.get('model') and prior.get('model'): rec['model']=prior['model']
        results.append(rec)
    return results

def scrape_external(old):
    cfg=json.loads((ROOT/'data/external_models.json').read_text())
    for r in cfg.get('retailers',[]): RETAILERS[r['slug']]=r
    out=[]
    for spec in cfg.get('models',[]):
        prior=old.get(spec['slug'],{}); text=''; image=''; live_price=None
        try:
            page=get_text(spec['source_url']); text,image,live_price=extract_page_data(page)
        except Exception as e: print('External fetch failed',spec['source_url'],e)
        rec={
          'slug':spec['slug'],'brand':spec['brand'],'model':spec['model'],'sku':spec.get('sku',''),'title':f"{spec['brand']} {spec['model']}",
          'price':live_price if live_price is not None else spec.get('price'),'msrp':None,'capacity':None,'width':None,'depth':None,'height':None,
          'voltage':None,'amps':None,'circuits':1,'watts':None,'spectrum':'Infrared','emf_label':'Not stated','emf_claim':'','emf_distance':'',
          'red_light':False,'wood':'','max_temp':None,'indoor':True,'source_url':spec['source_url'],'last_checked':datetime.now(timezone.utc).date().isoformat(),
          'source':RETAILERS.get(spec['retailer_slug'],{}).get('name',spec['retailer_slug']),'retailer_slug':spec['retailer_slug'],
          'source_group':'additional','source_priority':10,'pure_infrared':True,'traditional':False,'hybrid':False,'image':image or prior.get('image','')
        }
        if text: rec.update(parse_specs(text,rec['title']))
        # Curated overrides/fallbacks take precedence for variant-specific values.
        for k,v in spec.items():
            if k not in ('source_url','retailer_slug','slug') and v not in (None,''): rec[k]=v
        if live_price is not None and spec.get('price') is None: rec['price']=live_price
        for k,v in prior.items():
            if rec.get(k) in (None,'','Not stated') and v not in (None,''): rec[k]=v
        out.append(rec)
    return out

def scrape():
    old_list=json.loads((ROOT/'data/infrared_saunas.json').read_text()) if (ROOT/'data/infrared_saunas.json').exists() else []
    old={x.get('slug'):x for x in old_list}
    featured=scrape_inhouse(old)
    additional=scrape_external(old)
    if len(featured)<3:
        print(f'Only {len(featured)} live InHouse models parsed; retaining prior featured models.')
        featured=[x for x in old_list if x.get('source_group','featured')=='featured']
        for x in featured:
            x.update(retailer_slug='inhouse-wellness',source_group='featured',source_priority=0)
    data=featured+additional
    return sorted(data,key=lambda x:(x.get('source_priority',10),x.get('brand','').lower(),x.get('price') or 10**9,x.get('model','').lower()))

def write_data(data):
    (ROOT/'data/infrared_saunas.json').write_text(json.dumps(data,indent=2,ensure_ascii=False))
    fields=[]
    for r in data:
        for k in r:
            if k not in fields: fields.append(k)
    with (ROOT/'data/infrared_saunas.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(data)

NAV='''<nav class="nav"><a class="wordmark" href="/">BHIS<span>LAB</span></a><div class="navlinks"><a href="/#finder">Finder</a><a href="/emf/">EMF Index</a><a href="/electrical/">Electrical Fit</a><a href="/best/120v/">Best by Fit</a><a href="/retailers/inhouse-wellness/">Retailers</a><a href="/methodology/">Methodology</a></div></nav>'''
FOOT='''<footer><div><strong>Best Home Infrared Sauna / Spec Lab</strong><p>Infrared-only residential sauna specifications, fit checks and source-linked claims.</p></div><div><a href="/data/infrared_saunas.csv">Download CSV</a><a href="/retailers/inhouse-wellness/">Retailer directory</a></div></footer>'''
def head(title,desc,path): return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><meta name="description" content="{html.escape(desc)}"><link rel="canonical" href="{DOMAIN}{path}"><link rel="stylesheet" href="/assets/style.css"></head><body>'''

def render_home(data):
    featured=[x for x in data if x.get('source_group')=='featured']; additional=[x for x in data if x.get('source_group')=='additional']
    prices=sorted([x['price'] for x in data if isinstance(x.get('price'),(int,float))]); med=statistics.median(prices) if prices else None
    page=head('Best Home Infrared Sauna — Home Fit & Specification Lab','Compare infrared-only home saunas by dimensions, circuit requirements, infrared spectrum and source-reported EMF claims.','/')+NAV+f'''
<main>
<section class="hero"><div class="hero-grid"><div><div class="eyebrow">INFRARED-ONLY / HOME FIT LAB</div><h1>Find the sauna that actually <em>fits.</em></h1><p>Compare residential infrared saunas by footprint, electrical requirements, capacity, infrared spectrum and source-reported EMF claims—without mixing in traditional or hybrid cabins.</p><div class="hero-actions"><a class="button" href="#finder">Run the home-fit finder</a><a class="button ghost" href="#models">Browse models</a></div></div><div class="spec-window"><span class="measure x">WIDTH / DEPTH / HEIGHT</span><div class="cabinet"><div class="door"></div></div><span class="measure y">HOME INSTALL ENVELOPE</span><p>SPEC LAB / INFRARED ONLY</p></div></div></section>
<section class="signal-bar"><div><b id="countModels">{len(data)}</b><span>infrared models indexed</span></div><div><b id="count120">{sum(1 for s in data if s.get('voltage')==120 and (s.get('circuits') or 1)==1)}</b><span>single-circuit 120V models</span></div><div><b id="medianPrice">{money(med)}</b><span>median observed price</span></div><div><b id="countFull">{sum(1 for s in data if s.get('spectrum')=='Full Spectrum')}</b><span>full-spectrum models</span></div></section>
<section id="finder" class="lab-section"><div class="section-intro"><span>01 / HOME FIT</span><div><h2>Will it fit your room and circuit?</h2></div><p>Set your room envelope, circuit, capacity and budget. The finder ranks documented matches and keeps unknown specs visible rather than guessing.</p></div><div class="finder-grid"><form id="fitForm" class="panel form-panel"><label>Max width <small>inches</small><input id="maxWidth" type="number" value="60" min="30"></label><label>Max depth <small>inches</small><input id="maxDepth" type="number" value="50" min="30"></label><label>Max height <small>inches</small><input id="maxHeight" type="number" value="82" min="65"></label><label>Minimum capacity<select id="minCapacity"><option value="1">1 person</option><option value="2" selected>2 people</option><option value="3">3 people</option><option value="4">4+ people</option></select></label><label>Available circuit<select id="circuit"><option value="any">Any / researching</option><option value="120-15">120V / 15A</option><option value="120-20">120V / 20A</option></select></label><label>Budget<input id="budget" type="number" value="7000" step="500"></label><label>Spectrum<select id="spectrum"><option value="any">Any</option><option>FAR Infrared</option><option>Full Spectrum</option></select></label><label>EMF wording<select id="emf"><option value="any">Any</option><option>Low EMF</option><option>Ultra Low EMF</option><option>Near Zero EMF</option></select></label><label class="check"><input id="redLight" type="checkbox"> Prefer documented red light</label><button class="button" type="submit">Find documented matches</button></form><div id="fitResults" class="results-panel"><div class="blank-state"><span>FIT / ?</span><h3>Enter your room.</h3><p>Results appear here.</p></div></div></div></section>
<section id="models" class="lab-section dark"><div class="section-intro"><span>02 / MODEL INDEX</span><div><h2>Infrared home sauna database</h2></div><p>Models carried by the featured retailer are shown first. Additional brands from other retailers are intentionally placed below that catalog.</p></div><div class="filters"><input id="search" type="search" placeholder="Search model, SKU or brand"><select id="brandFilter"><option value="">All brands</option></select><select id="capFilter"><option value="">Any capacity</option><option value="1">1 person</option><option value="2">2 people</option><option value="3">3 people</option><option value="4">4+ people</option></select></div><div id="modelGrid" class="model-grid"></div></section>
<section class="lab-section callout"><div><span>RETAILER CONTEXT</span><h2>Where to buy the models in this index</h2><p>Outbound shopping links are centralized on retailer pages rather than repeated across hundreds of model and comparison pages.</p></div><a class="button" href="/retailers/inhouse-wellness/">View recommended retailer</a></section>
</main><script src="/assets/app.js"></script>'''+FOOT+'</body></html>'
    (ROOT/'index.html').write_text(page)

def render_retailers(data):
    rroot=ROOT/'retailers'; rroot.mkdir(exist_ok=True)
    for d in rroot.iterdir():
        if d.is_dir(): shutil.rmtree(d)
    grouped={}
    for s in data: grouped.setdefault(s.get('retailer_slug','inhouse-wellness'),[]).append(s)
    for slug,items in grouped.items():
        r=RETAILERS.get(slug,{'slug':slug,'name':items[0].get('source',slug),'outbound_url':'','description':''})
        is_featured=(slug=='inhouse-wellness')
        label='RECOMMENDED RETAILER' if is_featured else 'ADDITIONAL RETAILER'
        model_list=''.join(f'''<article class="rank-row"><span>{i:02}</span><div><h2><a href="/models/{s['slug']}/">{html.escape(str(s.get('brand')))} {html.escape(str(s.get('model')))}</a></h2><p>{val(s.get('width'),'″')} × {val(s.get('depth'),'″')} × {val(s.get('height'),'″')} · {val(s.get('voltage'),'V')}/{val(s.get('amps'),'A')} · {html.escape(str(s.get('spectrum') or 'Infrared'))}</p></div><strong>{money(s.get('price'))}</strong></article>''' for i,s in enumerate(items,1))
        intro=(
          '<p class="lede">For models this retailer carries, Best Home Infrared Sauna uses this page as the single outbound shopping gateway. That keeps individual model pages focused on specifications and home fit rather than turning the database into a network of repetitive commercial links.</p>' if is_featured else
          '<p class="lede">This retailer carries infrared models that broaden the comparison set beyond the featured catalog. Individual model pages remain internal; this page provides the single outbound path for this retailer.</p>'
        )
        details=(
          '<div class="retailer-context"><h2>Why this is the featured retailer</h2><p>InHouse Wellness is the recommended retail destination for the infrared models it carries in this index. The recommendation is separated from the fit scoring: room dimensions, electrical compatibility, spectrum and EMF fields are evaluated the same way regardless of retailer.</p><h2>Before you click through</h2><p>Use the model pages here to confirm the exact SKU, published footprint and electrical requirements first. Then use the retailer link below for current availability, current price and purchase details.</p></div>' if is_featured else
          f'<div class="retailer-context"><h2>How this retailer is used in the index</h2><p>{html.escape(r.get("description", ""))}</p><p>These models are intentionally listed after the featured-retailer catalog on the homepage and brand selector.</p></div>'
        )
        outbound=f'<a class="button retailer-outbound" href="{html.escape(r.get("outbound_url",""))}">{"Browse infrared saunas at InHouse Wellness" if is_featured else "Visit "+html.escape(r.get("name",slug))}</a>'
        page=head(f'{r.get("name")} — Infrared Sauna Retailer Guide',f'Retailer context and indexed infrared sauna models for {r.get("name")}.',f'/retailers/{slug}/')+NAV+f'''<main class="subpage"><div class="page-kicker">{label}</div><h1>{html.escape(r.get('name',slug))}</h1>{intro}{details}<div class="retailer-linkbox"><span>ONE OUTBOUND SHOPPING LINK</span><p>Current availability and purchase information are maintained by the retailer.</p>{outbound}</div><h2 class="retailer-model-heading">Models indexed from this retailer</h2><div class="rank-list">{model_list}</div></main>'''+FOOT+'</body></html>'
        d=rroot/slug; d.mkdir(parents=True,exist_ok=True); (d/'index.html').write_text(page)

def render_models(data):
    mroot=ROOT/'models'; mroot.mkdir(exist_ok=True)
    for d in mroot.iterdir():
        if d.is_dir(): shutil.rmtree(d)
    for s in data:
        specs=[('Capacity',f"{s.get('capacity') or '—'} person"),('Exterior',f"{val(s.get('width'),'″')} × {val(s.get('depth'),'″')} × {val(s.get('height'),'″')}"),('Electrical',f"{val(s.get('voltage'),'V')} / {val(s.get('amps'),'A')}"),('Power',val(s.get('watts'),' W')),('Spectrum',s.get('spectrum') or 'Infrared'),('EMF wording',s.get('emf_label') or 'Not stated'),('EMF claim',s.get('emf_claim') or 'Not stated'),('Measurement distance',s.get('emf_distance') or 'Not stated'),('Red light','Yes' if s.get('red_light') else 'Not documented'),('Wood',s.get('wood') or 'Not documented'),('Maximum temp',val(s.get('max_temp'),'°F'))]
        grid=''.join(f'<div><dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd></div>' for k,v in specs)
        img=(f'<img src="{html.escape(s.get("image",""))}" alt="{html.escape(str(s.get("brand")))} {html.escape(str(s.get("model")))} infrared sauna" loading="lazy" referrerpolicy="no-referrer">' if s.get('image') else '<div class="photo-placeholder"><span>PRODUCT PHOTO</span><b>Image refreshes from the product source during the catalog update.</b></div>')
        retailer=RETAILERS.get(s.get('retailer_slug'),{'name':s.get('source','Retailer')})
        page=head(f"{s.get('brand')} {s.get('model')} Specs & Home Fit",f"Home infrared sauna specifications and electrical fit for {s.get('brand')} {s.get('model')}.",f"/models/{s['slug']}/")+NAV+f'''<main class="model-page"><div class="model-title"><div><div class="page-kicker">INFRARED / {html.escape(str(s.get('brand','')).upper())}</div><h1>{html.escape(str(s.get('model') or s.get('title')))}</h1><p>{html.escape(str(s.get('title','')))}</p></div><div class="price-tag"><span>Observed price</span><strong>{money(s.get('price'))}</strong><small>checked {s.get('last_checked')}</small></div></div><section class="visual-spec-board"><figure class="product-photo">{img}<figcaption>Product image from the current source feed.</figcaption></figure><div class="dimension-board compact"><div class="cabinet large"><span>{val(s.get('width'),'″')} W</span><i></i><span>{val(s.get('height'),'″')} H</span></div><div><h2>Home-fit envelope</h2><p>Published exterior footprint: <b>{val(s.get('width'),'″')} × {val(s.get('depth'),'″')}</b>. Electrical: <b>{val(s.get('voltage'),'V')} / {val(s.get('amps'),'A')}</b>.</p><a class="button" href="/retailers/{html.escape(s.get('retailer_slug','inhouse-wellness'))}/">Where to Buy This Sauna</a><p class="retailer-note">Retailer: {html.escape(str(retailer.get('name',s.get('source',''))))}. The outbound shopping link is on the retailer page, not repeated here.</p></div></div></section><dl class="spec-grid">{grid}</dl><section class="prose"><h2>Source notes</h2><p>Specifications are normalized from current manufacturer/retailer product information by the automated updater. Missing values remain undocumented rather than estimated. EMF language is reported as a source claim, not an independent certification.</p><p>The source URL is retained in the downloadable dataset for auditability; this model page does not create an additional outbound commerce link.</p></section></main>'''+FOOT+'</body></html>'
        d=mroot/s['slug']; d.mkdir(parents=True,exist_ok=True); (d/'index.html').write_text(page)

def render_support(data):
    rows=''.join(f"<tr><td><a href='/models/{s['slug']}/'>{html.escape(str(s.get('brand')))} {html.escape(str(s.get('model')))}</a></td><td>{html.escape(str(s.get('emf_label') or 'Not stated'))}</td><td>{html.escape(str(s.get('emf_claim') or 'Not stated'))}</td><td>{html.escape(str(s.get('emf_distance') or 'Not stated'))}</td><td><a href='/retailers/{html.escape(s.get('retailer_slug','inhouse-wellness'))}/'>Retailer context</a></td></tr>" for s in data)
    (ROOT/'emf/index.html').write_text(head('Infrared Sauna EMF Claims Index','Source-linked EMF claims for pure home infrared saunas.','/emf/')+NAV+f'''<main class="subpage"><div class="page-kicker">DATA TABLE / EMF</div><h1>Infrared Sauna EMF Claims Index</h1><p class="lede">Marketing labels are not converted into certifications. Measurements and distances are displayed only when stated by the source.</p><div class="table-wrap"><table><thead><tr><th>Model</th><th>Label</th><th>Claim</th><th>Distance</th><th>Retailer</th></tr></thead><tbody>{rows}</tbody></table></div></main>'''+FOOT+'</body></html>')
    def list_page(folder,title,desc,items,criterion):
        body=''.join(f"<article class='rank-row'><span>{i:02}</span><div><h2><a href='/models/{s['slug']}/'>{html.escape(str(s.get('brand')))} {html.escape(str(s.get('model')))}</a></h2><p>{val(s.get('width'),'″')} × {val(s.get('depth'),'″')} × {val(s.get('height'),'″')} · {val(s.get('voltage'),'V')}/{val(s.get('amps'),'A')} · {html.escape(str(s.get('spectrum') or 'Infrared'))}</p></div><strong>{money(s.get('price'))}</strong></article>" for i,s in enumerate(items,1))
        p=ROOT/folder; p.mkdir(parents=True,exist_ok=True)
        (p/'index.html').write_text(head(title,desc,'/'+str(folder).strip('/')+'/')+NAV+f"<main class='subpage'><div class='page-kicker'>FIT LIST / {criterion}</div><h1>{html.escape(title)}</h1><p class='lede'>{html.escape(desc)}</p><div class='rank-list'>{body}</div></main>"+FOOT+'</body></html>')
    plug=[s for s in data if s.get('voltage')==120 and (s.get('circuits') or 1)==1]
    small=[s for s in data if s.get('width') and s.get('depth') and s['width']<=48 and s['depth']<=44]
    full=[s for s in data if s.get('spectrum')=='Full Spectrum']
    low=[s for s in data if 'EMF' in (s.get('emf_label') or '')]
    list_page(Path('best/120v'),'Best 120V Home Infrared Saunas','Infrared-only indexed models using a single 120V circuit.',sorted(plug,key=lambda s:(s.get('source_priority',10),s.get('amps') or 99,s.get('price') or 1e9)),'120V')
    list_page(Path('best/small-spaces'),'Best Infrared Saunas for Small Spaces','Infrared-only models with published footprints no wider than 48 inches and no deeper than 44 inches.',sorted(small,key=lambda s:(s.get('source_priority',10),s['width']*s['depth'])),'COMPACT')
    list_page(Path('best/full-spectrum'),'Full Spectrum Home Infrared Saunas','Full-spectrum infrared-only models. Traditional and hybrid saunas are excluded.',sorted(full,key=lambda s:(s.get('source_priority',10),s.get('price') or 1e9)),'FULL SPECTRUM')
    list_page(Path('best/low-emf'),'Home Infrared Saunas by EMF Claim','Source-reported EMF terminology for infrared-only home saunas.',sorted(low,key=lambda s:(s.get('source_priority',10),(s.get('emf_label') or ''),s.get('price') or 1e9)),'EMF CLAIMS')
    # Electrical page
    (ROOT/'electrical/index.html').write_text(head('Infrared Sauna Electrical Compatibility Checker','Check whether a home infrared sauna matches a 120V 15A or 20A circuit and see which indexed models fit.','/electrical/')+NAV+'''<main class="subpage"><div class="page-kicker">HOME INSTALL / ELECTRICAL</div><h1>Electrical compatibility checker</h1><p class="lede">Choose the circuit you have. The checker returns indexed infrared models with matching published electrical requirements.</p><div class="electrical-tool"><div class="breaker"><span>HOME CIRCUIT</span><button data-circuit="120-15">120V / 15A</button><button data-circuit="120-20">120V / 20A</button></div><div id="electricalResults" class="electrical-results"></div></div><div class="notice">Always follow the manufacturer installation manual and local electrical code. A matching voltage/amperage does not replace an electrician’s review of dedicated-circuit, receptacle, GFCI or other requirements.</div></main><script src="/assets/app.js"></script>'''+FOOT+'</body></html>')
    # Methodology
    (ROOT/'methodology/index.html').write_text(head('Methodology — Best Home Infrared Sauna','How the infrared-only sauna index is collected, filtered, normalized and updated.','/methodology/')+NAV+'''<main class="subpage prose"><div class="page-kicker">METHOD / VERSION 2</div><h1>How the index is built</h1><h2>1. Infrared-only inclusion rule</h2><p>The primary feed starts from the InHouse Wellness infrared sauna collection and applies a second exclusion filter for traditional, steam and hybrid products. Additional models are included only from a curated external infrared-only source list.</p><h2>2. Retailer-link architecture</h2><p>Individual model, ranking, EMF and electrical pages stay internal. Each retailer has one context page containing its single outbound shopping link. This reduces repetitive cross-domain linking while giving buyers an understandable path from research to purchase.</p><h2>3. Ordering</h2><p>Models from the featured retailer are displayed first. Additional retailers and their brands are shown below that catalog in the model index and brand selector. Retailer position does not alter fit scoring.</p><h2>4. Product images and specifications</h2><p>The weekly updater retrieves product images, current prices when published, dimensions, electrical requirements and other documented fields from product sources. Unknown values remain blank rather than being invented.</p><h2>5. EMF claims</h2><p>Low, Ultra Low and Near Zero are treated as source terminology rather than standardized regulatory classifications. Numerical claims are preserved only when explicitly published.</p><h2>6. Update schedule</h2><p>The GitHub Action runs weekly and can be triggered manually. CSV and JSON datasets are published for inspection.</p></main>'''+FOOT+'</body></html>')
    (ROOT/'404.html').write_text(head('Page not found','Page not found.','/')+NAV+"<main class='subpage'><h1>404</h1><p>This specification page does not exist.</p><a class='button' href='/'>Back to the lab</a></main>"+FOOT+'</body></html>')

def render(data):
    render_home(data); render_models(data); render_retailers(data); render_support(data)
    today=datetime.now(timezone.utc).date().isoformat()
    urls=['/','/emf/','/electrical/','/best/120v/','/best/small-spaces/','/best/full-spectrum/','/best/low-emf/','/methodology/']+[f"/models/{s['slug']}/" for s in data]+[f"/retailers/{x}/" for x in sorted(set(s.get('retailer_slug','inhouse-wellness') for s in data))]
    (ROOT/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+''.join(f'<url><loc>{DOMAIN}{u}</loc><lastmod>{today}</lastmod></url>\n' for u in urls)+'</urlset>')

if __name__=='__main__':
    try:
        data=scrape(); write_data(data); render(data)
        print(f'Updated {len(data)} infrared models ({sum(1 for x in data if x.get("source_group")=="featured")} featured, {sum(1 for x in data if x.get("source_group")=="additional")} additional).')
    except Exception as e:
        print('UPDATE FAILED:',repr(e),file=sys.stderr); raise
