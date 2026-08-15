#!/usr/bin/env python3
from pathlib import Path
import requests, json, csv, re, html, statistics, sys
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
BASE='https://inhousewellness.com'
COLLECTION=f'{BASE}/collections/infrared-saunas'
DOMAIN='https://besthomeinfraredsauna.com'
UA={'User-Agent':'Mozilla/5.0 (compatible; BestHomeInfraredSaunaBot/1.0; +https://besthomeinfraredsauna.com/methodology/)'}

NEGATIVE=('traditional','hybrid','steam sauna','wood-burning','wood burning')
INFRARED=('infrared','far ir','far infrared','full spectrum','nir ','near infrared')

def get_json(url):
    r=requests.get(url,headers=UA,timeout=35); r.raise_for_status(); return r.json()
def get_text(url):
    r=requests.get(url,headers=UA,timeout=35); r.raise_for_status(); return r.text

def clean(txt): return re.sub(r'\s+',' ',txt or '').strip()
def slugify(s):
    s=re.sub(r'[^a-z0-9]+','-',(s or '').lower()).strip('-')
    return s[:90] or 'infrared-sauna'

def pure_infrared(p):
    title=clean(p.get('title','')).lower()
    product_type=clean(p.get('product_type','')).lower()
    tags=p.get('tags',[])
    if isinstance(tags,str): tags=[tags]
    tagtext=' '.join(map(str,tags)).lower()
    structural=' '.join([title,product_type,tagtext])
    if any(x in structural for x in NEGATIVE): return False
    body=clean(p.get('body_html','')).lower()
    positive=' '.join([structural,body[:3000]])
    return any(x in positive for x in INFRARED)

def parse_num(pattern,text,flags=re.I):
    m=re.search(pattern,text,flags)
    return float(m.group(1)) if m else None

def parse_specs(text,title=''):
    t=clean(text)
    low=t.lower()
    out={}
    # Capacity — favor title, then body.
    m=re.search(r'(\d+)\s*(?:-|–)?\s*person',title,re.I) or re.search(r'(\d+)\s*(?:-|–)?\s*person',t,re.I)
    if m: out['capacity']=int(m.group(1))
    elif re.search(r'1\s*(?:to|–|-)\s*2\s*person',t,re.I): out['capacity']=2
    # Exterior dimension formats.
    patterns=[
      r'Exterior\s+(?:Dimensions?|dimensions?).{0,50}?(\d+(?:\.\d+)?)\s*(?:"|″|in(?:ches)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:"|″|in(?:ches)?)\s*[x×]\s*(\d+(?:\.\d+)?)',
      r'Exterior[^\n]{0,60}?Width\s*[:\-]?\s*(\d+(?:\.\d+)?)[^\n]{0,60}?Depth\s*[:\-]?\s*(\d+(?:\.\d+)?)[^\n]{0,60}?Height\s*[:\-]?\s*(\d+(?:\.\d+)?)'
    ]
    for p in patterns:
        m=re.search(p,t,re.I)
        if m:
            out.update(width=float(m.group(1)),depth=float(m.group(2)),height=float(m.group(3))); break
    # WDH variant where order is explicit in label; also common plain line.
    if not out.get('width'):
        m=re.search(r'Exterior dimensions\s*\(WDH\)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|″)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:"|″)?\s*[x×]\s*(\d+(?:\.\d+)?)',t,re.I)
        if m: out.update(width=float(m.group(1)),depth=float(m.group(2)),height=float(m.group(3)))
    # Electrical.
    m=re.search(r'(120|220|240)\s*(?:V|volt)[^\d]{0,20}(\d{1,2})\s*(?:A|amp)',t,re.I)
    if not m: m=re.search(r'(120|220|240)\s*V\s*/\s*(\d{1,2})\s*A',t,re.I)
    if m: out.update(voltage=int(m.group(1)),amps=int(m.group(2)))
    if re.search(r'two\s+dedicated\s+120',low) or re.search(r'2\s+(?:dedicated\s+)?120',low): out['circuits']=2
    elif out.get('voltage'): out['circuits']=1
    m=re.search(r'(\d{3,5})\s*(?:watts|watt|W\b)',t,re.I)
    if m: out['watts']=int(m.group(1))
    # Spectrum.
    if 'full spectrum' in low: out['spectrum']='Full Spectrum'
    elif 'far infrared' in low or 'far ir' in low: out['spectrum']='FAR Infrared'
    else: out['spectrum']='Infrared'
    # EMF wording: most specific first.
    if 'near zero emf' in low or 'near-zero emf' in low: out['emf_label']='Near Zero EMF'
    elif 'ultra low emf' in low or 'ultra-low emf' in low: out['emf_label']='Ultra Low EMF'
    elif 'low emf' in low or 'low-emf' in low: out['emf_label']='Low EMF'
    else: out['emf_label']='Not stated'
    # Nearby mG claim and measurement distance.
    mm=re.search(r'((?:under|less than|below|between)?\s*\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s*mG)',t,re.I)
    if mm: out['emf_claim']=clean(mm.group(1))
    dm=re.search(r'(\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s*(?:inches|inch|in|″))\s+(?:from|away)',t,re.I)
    if dm: out['emf_distance']=clean(dm.group(1))+' from heater/panel'
    out['red_light']='red light' in low or 'red-light' in low
    # materials
    if 'canadian hemlock' in low: out['wood']='Canadian Hemlock'
    elif 'cedar' in low and 'aspen' in low: out['wood']='Cedar / Aspen'
    elif 'cedar' in low: out['wood']='Cedar'
    # max temperature
    vals=[int(x) for x in re.findall(r'(?:max(?:imum)?(?: temperature)?[^\d]{0,20}|up to\s*)(1[1-9]\d)\s*°?F',t,re.I)]
    if vals: out['max_temp']=max(vals)
    return out

def model_name(title,sku):
    # quoted model names are useful; otherwise identifier; otherwise remove generic words.
    q=re.search(r'["“]([^"”]{2,30})["”]',title)
    if q: return q.group(1)
    if sku: return sku
    x=re.sub(r'\b(?:infrared|sauna|far|emf|low|ultra|near|zero|person|full spectrum|red light|therapy)\b',' ',title,flags=re.I)
    x=clean(re.sub(r'\s+',' ',x))
    return x[:45]

def product_urls():
    # Preferred Shopify collection JSON.
    try:
        data=get_json(COLLECTION+'/products.json?limit=250')
        products=data.get('products',[])
        if products: return products
    except Exception as e: print('Collection JSON unavailable:',e)
    # HTML fallback, then product .js endpoint.
    page=get_text(COLLECTION)
    soup=BeautifulSoup(page,'html.parser')
    handles=[]
    for a in soup.select('a[href*="/products/"]'):
        href=a.get('href','').split('?')[0]
        if '/products/' in href:
            handle=href.split('/products/',1)[1].strip('/')
            if handle and handle not in handles: handles.append(handle)
    products=[]
    for handle in handles:
        try:
            p=get_json(f'{BASE}/products/{handle}.js')
            p['handle']=handle; products.append(p)
        except Exception as e: print('Skip',handle,e)
    return products

def first_variant(p):
    vs=p.get('variants') or []
    available=[v for v in vs if v.get('available',True)]
    return (available or vs or [{}])[0]

def cents_or_float(v):
    if v in (None,''): return None
    try:
        n=float(v)
        return round(n/100,2) if n>100000 or (isinstance(v,int) and n>1000) else n
    except: return None

def scrape():
    old={x.get('retailer_url'):x for x in json.loads((ROOT/'data/infrared_saunas.json').read_text())} if (ROOT/'data/infrared_saunas.json').exists() else {}
    results=[]
    for p in product_urls():
        if not pure_infrared(p):
            print('Excluded non-pure-infrared:',p.get('title')); continue
        handle=p.get('handle') or slugify(p.get('title'))
        url=f'{BASE}/products/{handle}'
        try:
            page=get_text(url); text=BeautifulSoup(page,'html.parser').get_text(' ',strip=True)
        except Exception as e:
            print('Page fetch failed',url,e); text=BeautifulSoup(p.get('body_html',''),'html.parser').get_text(' ',strip=True)
        v=first_variant(p)
        # Shopify products.json returns price strings in dollars; .js often cents. detect by type/value.
        price=v.get('price')
        compare=v.get('compare_at_price')
        if isinstance(price,int): price=price/100
        else:
            try: price=float(price) if price not in (None,'') else None
            except: price=None
        if isinstance(compare,int): compare=compare/100
        else:
            try: compare=float(compare) if compare not in (None,'') else None
            except: compare=None
        sku=clean(v.get('sku',''))
        title=clean(p.get('title',''))
        vendor=clean(p.get('vendor','')) or 'Unknown'
        rec={
          'slug':slugify((sku or handle)),'brand':vendor,'model':model_name(title,sku),'sku':sku,'title':title,
          'price':price,'msrp':compare,'capacity':None,'width':None,'depth':None,'height':None,'voltage':None,'amps':None,'circuits':None,'watts':None,
          'spectrum':'Infrared','emf_label':'Not stated','emf_claim':'','emf_distance':'','red_light':False,'wood':'','max_temp':None,'indoor':True,
          'retailer_url':url,'source_url':url,'last_checked':datetime.now(timezone.utc).date().isoformat(),'source':'InHouse Wellness','pure_infrared':True,'traditional':False,'hybrid':False,
          'image':((p.get('images') or [{}])[0].get('src') if isinstance((p.get('images') or [{}])[0],dict) else (p.get('images') or [''])[0]) or ''
        }
        rec.update(parse_specs(text,title))
        # Merge trustworthy old values when fresh parsing leaves a hole.
        prior=old.get(url,{})
        for k in ('capacity','width','depth','height','voltage','amps','circuits','watts','emf_claim','emf_distance','wood','max_temp','sku','image'):
            if rec.get(k) in (None,'','Not stated') and prior.get(k) not in (None,''):
                rec[k]=prior[k]
        if rec['model']=='' and prior.get('model'): rec['model']=prior['model']
        results.append(rec)
    return sorted(results,key=lambda x:(x.get('brand',''),x.get('price') or 10**9,x.get('model','')))

def write_data(data):
    (ROOT/'data/infrared_saunas.json').write_text(json.dumps(data,indent=2,ensure_ascii=False))
    fields=list(data[0].keys()) if data else []
    if fields:
        with (ROOT/'data/infrared_saunas.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)

def money(x): return f'${x:,.0f}' if isinstance(x,(int,float)) else '—'
def val(x,s=''): return f'{x:g}{s}' if isinstance(x,float) else (f'{x}{s}' if x not in (None,'') else '—')
NAV='''<nav class="nav"><a class="wordmark" href="/">BHIS<span>LAB</span></a><div class="navlinks"><a href="/#finder">Finder</a><a href="/emf/">EMF Index</a><a href="/electrical/">Electrical Fit</a><a href="/best/120v/">Best by Fit</a><a href="/methodology/">Methodology</a></div></nav>'''
FOOT='''<footer><div><strong>Best Home Infrared Sauna / Spec Lab</strong><p>Infrared-only residential sauna specifications, fit checks and source-linked claims.</p></div><div><a href="/data/infrared_saunas.csv">Download CSV</a><a href="https://inhousewellness.com/collections/infrared-saunas">Shop infrared saunas at InHouse Wellness</a></div></footer>'''
def head(title,desc,path): return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><meta name="description" content="{html.escape(desc)}"><link rel="canonical" href="{DOMAIN}{path}"><link rel="stylesheet" href="/assets/style.css"></head><body>'''

def render(data):
    today=datetime.now(timezone.utc).date().isoformat()
    # Delete old generated model dirs to prevent traditional/stale imports lingering.
    mroot=ROOT/'models'; mroot.mkdir(exist_ok=True)
    for d in mroot.iterdir():
        if d.is_dir():
            for f in d.rglob('*'):
                if f.is_file(): f.unlink()
            try: d.rmdir()
            except: pass
    for s in data:
        circuits=(s.get('circuits') or 1)
        specs=[('Capacity',f"{s.get('capacity') or '—'} person"),('Exterior',f"{val(s.get('width'),'″')} × {val(s.get('depth'),'″')} × {val(s.get('height'),'″')}"),('Electrical',f"{val(s.get('voltage'),'V')} / {val(s.get('amps'),'A')}"+(f' × {circuits} circuits' if circuits>1 else '')),('Power',val(s.get('watts'),' W')),('Spectrum',s.get('spectrum') or 'Infrared'),('EMF wording',s.get('emf_label') or 'Not stated'),('EMF claim',s.get('emf_claim') or 'Not stated'),('Measurement distance',s.get('emf_distance') or 'Not stated'),('Red light','Yes' if s.get('red_light') else 'Not documented'),('Wood',s.get('wood') or 'Not documented'),('Maximum temp',val(s.get('max_temp'),'°F'))]
        grid=''.join(f'<div><dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd></div>' for k,v in specs)
        page=head(f"{s.get('brand')} {s.get('model')} Specs & Home Fit",f"Home infrared sauna specifications and electrical fit for {s.get('brand')} {s.get('model')}.",f"/models/{s['slug']}/")+NAV+f'''<main class="model-page"><div class="model-title"><div><div class="page-kicker">INFRARED / {html.escape(str(s.get('brand','')).upper())}</div><h1>{html.escape(str(s.get('model') or s.get('title')))}</h1><p>{html.escape(str(s.get('title','')))}</p></div><div class="price-tag"><span>Observed price</span><strong>{money(s.get('price'))}</strong><small>checked {s.get('last_checked')}</small></div></div><section class="dimension-board"><div class="cabinet large"><span>{val(s.get('width'),'″')} W</span><i></i><span>{val(s.get('height'),'″')} H</span></div><div><h2>Home-fit envelope</h2><p>Published exterior footprint: <b>{val(s.get('width'),'″')} × {val(s.get('depth'),'″')}</b>. Electrical: <b>{val(s.get('voltage'),'V')} / {val(s.get('amps'),'A')}</b>.</p><a class="button" href="{html.escape(s.get('retailer_url',''))}" rel="sponsored">View at InHouse Wellness</a></div></section><dl class="spec-grid">{grid}</dl><section class="prose"><h2>Source notes</h2><p>Generated from source-linked product data. Missing values remain undocumented rather than estimated. EMF language is reported as a source claim, not an independent certification.</p><p><a href="{html.escape(s.get('source_url',''))}">Open current source →</a></p></section></main>'''+FOOT+'</body></html>'
        d=mroot/s['slug'];d.mkdir(parents=True,exist_ok=True);(d/'index.html').write_text(page)
    # EMF table
    rows=''.join(f"<tr><td><a href='/models/{s['slug']}/'>{html.escape(str(s.get('brand')))} {html.escape(str(s.get('model')))}</a></td><td>{html.escape(str(s.get('emf_label') or 'Not stated'))}</td><td>{html.escape(str(s.get('emf_claim') or 'Not stated'))}</td><td>{html.escape(str(s.get('emf_distance') or 'Not stated'))}</td><td><a href='{html.escape(s.get('source_url',''))}'>Source</a></td></tr>" for s in data)
    (ROOT/'emf/index.html').write_text(head('Infrared Sauna EMF Claims Index','Source-linked EMF claims for pure home infrared saunas.','/emf/')+NAV+f'''<main class="subpage"><div class="page-kicker">DATA TABLE / EMF</div><h1>Infrared Sauna EMF Claims Index</h1><p class="lede">Marketing labels are not converted into certifications. Measurements and distances are displayed only when stated by the source.</p><div class="table-wrap"><table><thead><tr><th>Model</th><th>Label</th><th>Claim</th><th>Distance</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div></main>'''+FOOT+'</body></html>')
    def list_page(folder,title,desc,items,criterion):
        body=''.join(f"<article class='rank-row'><span>{i:02}</span><div><h2><a href='/models/{s['slug']}/'>{html.escape(str(s.get('brand')))} {html.escape(str(s.get('model')))}</a></h2><p>{val(s.get('width'),'″')} × {val(s.get('depth'),'″')} × {val(s.get('height'),'″')} · {val(s.get('voltage'),'V')}/{val(s.get('amps'),'A')} · {html.escape(str(s.get('spectrum') or 'Infrared'))}</p></div><strong>{money(s.get('price'))}</strong></article>" for i,s in enumerate(items,1))
        (ROOT/folder/'index.html').write_text(head(title,desc,'/'+str(folder).strip('/')+'/')+NAV+f"<main class='subpage'><div class='page-kicker'>FIT LIST / {criterion}</div><h1>{html.escape(title)}</h1><p class='lede'>{html.escape(desc)}</p><div class='rank-list'>{body}</div></main>"+FOOT+'</body></html>')
    plug=[s for s in data if s.get('voltage')==120 and (s.get('circuits') or 1)==1]
    small=[s for s in data if s.get('width') and s.get('depth') and s['width']<=48 and s['depth']<=44]
    full=[s for s in data if s.get('spectrum')=='Full Spectrum']
    low=[s for s in data if 'EMF' in (s.get('emf_label') or '')]
    list_page(Path('best/120v'),'Best 120V Home Infrared Saunas','Infrared-only indexed models using a single 120V circuit.',sorted(plug,key=lambda s:(s.get('amps') or 99,s.get('price') or 1e9)),'120V')
    list_page(Path('best/small-spaces'),'Best Infrared Saunas for Small Spaces','Infrared-only models with published footprints no wider than 48 inches and no deeper than 44 inches.',sorted(small,key=lambda s:s['width']*s['depth']),'COMPACT')
    list_page(Path('best/full-spectrum'),'Full Spectrum Home Infrared Saunas','Full-spectrum infrared-only models. Traditional and hybrid saunas are excluded.',sorted(full,key=lambda s:s.get('price') or 1e9),'FULL SPECTRUM')
    list_page(Path('best/low-emf'),'Home Infrared Saunas by EMF Claim','Source-reported EMF terminology for infrared-only home saunas.',sorted(low,key=lambda s:((s.get('emf_label') or ''),s.get('price') or 1e9)),'EMF CLAIMS')
    urls=['/','/emf/','/electrical/','/best/120v/','/best/small-spaces/','/best/full-spectrum/','/best/low-emf/','/methodology/']+[f"/models/{s['slug']}/" for s in data]
    (ROOT/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+''.join(f'<url><loc>{DOMAIN}{u}</loc><lastmod>{today}</lastmod></url>\n' for u in urls)+'</urlset>')

if __name__=='__main__':
    try:
        data=scrape()
        if len(data)<3: raise RuntimeError(f'Only {len(data)} infrared products parsed; refusing to overwrite working dataset.')
        write_data(data); render(data)
        print(f'Updated {len(data)} pure infrared models. Traditional/hybrid/steam products excluded.')
    except Exception as e:
        print('UPDATE FAILED:',repr(e),file=sys.stderr); raise
