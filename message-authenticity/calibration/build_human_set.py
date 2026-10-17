import json, re, urllib.request, random
random.seed(7)
def rows(ds, offset, n=100, config='default', split='train'):
    u=f'https://datasets-server.huggingface.co/rows?dataset={ds}&config={config}&split={split}&offset={offset}&length={n}'
    return json.load(urllib.request.urlopen(u, timeout=60))['rows']
def clean(t):
    t=re.sub(r'https?://\S+|@\w+|#\w+','',t).strip()
    return re.sub(r'\s+',' ',t)
def words(t): return len(t.split())
out={'en':[], 'fr':[]}
# FR: tweets + youtube comments
for ds in ('FrancophonIA/french_tweets','GwendalTsang/French_Youtube_Comments'):
    for off in range(0, 3000, 100):
        try: rs=rows(ds, off)
        except Exception as e: print(ds,off,e); break
        for r in rs:
            for v in r['row'].values():
                if isinstance(v,str):
                    t=clean(v)
                    if 14<=words(t)<=70: out['fr'].append({'source':ds,'text':t})
        if len(out['fr'])>400: break
# EN: yelp reviews (informal human text)
for off in range(0, 3000, 100):
    try: rs=rows('Yelp/yelp_review_full', off)
    except Exception as e: print('yelp',off,e); break
    for r in rs:
        t=clean(r['row'].get('text',''))
        if 14<=words(t)<=70: out['en'].append({'source':'Yelp/yelp_review_full','text':t})
    if len(out['en'])>400: break
for k in out:
    random.shuffle(out[k]); out[k]=out[k][:80]
    print(k,len(out[k]))
json.dump(out, open('human.json','w'), ensure_ascii=False, indent=1)
