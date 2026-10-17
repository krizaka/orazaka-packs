"""Builds the generated half of the set: first messages on a dating app, written through Orazaka (chat), in EN and FR, varied tone/length/style."""
import json, os, random, re, subprocess, urllib.request, uuid, time
random.seed(5)
U=os.environ['AI_ENGINE_URL']; K=os.environ['AI_ENGINE_API_KEY']  # Orazaka's edge and a service key
def chat(prompt):
    cid=str(uuid.uuid4())
    req=urllib.request.Request(f'{U}/api/v1/chat/stream/{cid}',method='POST',data=json.dumps({'prompt':prompt}).encode(),headers={'Authorization':'Bearer '+K,'Content-Type':'application/json'})
    body=urllib.request.urlopen(req,timeout=90).read().decode()
    text=''
    for blk in body.split('\n\n'):
        ev='message'; data=[]
        for l in blk.split('\n'):
            if l.startswith('event:'): ev=l[6:].strip()
            elif l.startswith('data:'): data.append(l[5:].lstrip())
        if ev=='message' and data:
            try: text+=json.loads('\n'.join(data)).get('content','')
            except Exception: pass
    try: urllib.request.urlopen(urllib.request.Request(f'{U}/api/v1/chat/sessions/{cid}',method='DELETE',headers={'Authorization':'Bearer '+K}),timeout=20)
    except Exception: pass
    return text.strip()
topics=['hiking and trying new restaurants','books and rainy Sundays','cooking for friends','travel and street photography','live music and small venues','cycling along the river','board games and bad puns','gardening and farmers markets','climbing and coffee','movies and long walks with a dog']
topics_fr=['la randonnée et les nouveaux restos','les livres et les dimanches de pluie','cuisiner pour des amis','les voyages et la photo de rue','la musique live et les petites salles','le vélo le long du fleuve','les jeux de société et les jeux de mots nuls','le jardinage et les marchés','l’escalade et le café','le cinéma et les balades avec un chien']
tones=['warm and curious','playful and a bit teasing','calm and sincere','short and direct','enthusiastic']
styles=['','', 'Write it as a real person would text: casual, lowercase start, no emoji, one tiny imperfection.','Make it sound human and spontaneous, not polished.']
def prompt(lang, i):
    n=random.choice([14,20,28,40,55])
    if lang=='en':
        base=f"Write a first message from someone to a person they just matched with on a dating app. They both like {random.choice(topics)}. Tone: {random.choice(tones)}. About {n} words. {random.choice(styles)} Reply with the message only, no quotes."
    else:
        base=f"Écris le premier message d’une personne à quelqu’un avec qui elle vient de matcher sur une appli de rencontre. Ils aiment tous les deux {random.choice(topics_fr)}. Ton : {random.choice(['chaleureux et curieux','joueur et un peu taquin','calme et sincère','court et direct','enthousiaste'])}. Environ {n} mots. {random.choice(['','','Écris-le comme une vraie personne qui textote, décontracté, sans emoji, une petite imperfection.','Fais-le sonner humain et spontané, pas poli.'])} Réponds uniquement par le message, sans guillemets, en français (québécois, avec « tu »)."
    return base
out={'en':[],'fr':[]}
for lang in ('en','fr'):
    while len(out[lang])<80:
        p=prompt(lang,len(out[lang]))
        try: t=chat(p)
        except Exception as e: print('err',e); time.sleep(3); continue
        t=re.sub(r'^["«»\s]+|["«»\s]+$','',t)
        if 10<=len(t.split())<=90: out[lang].append({'source':'orazaka-chat (do-inference default model)','text':t,'prompt':p})
        if len(out[lang])%20==0: print(lang,len(out[lang]),flush=True)
json.dump(out,open('generated.json','w'),ensure_ascii=False,indent=1)
