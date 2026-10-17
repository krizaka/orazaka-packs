import json, sys, math
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
MODELS = {'fakespot-roberta': 'fakespot-ai/roberta-base-ai-text-detection-v1', 'bibbbu-xlmr': 'bibbbu/multilingual-ai-human-detector_xlm-roberta-base'}
human = json.load(open('human.json')); gen = json.load(open('generated.json'))
def auc(pos, neg):
    s = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg); return s / (len(pos) * len(neg))
res = {}
for key, repo in MODELS.items():
    tok = AutoTokenizer.from_pretrained(repo); model = AutoModelForSequenceClassification.from_pretrained(repo).eval()
    labels = model.config.id2label; print(key, labels, flush=True)
    ai_idx = next((i for i, l in labels.items() if str(l).lower() in ('ai', 'ai-generated', 'generated', 'label_1', 'machine', 'fake', '1')), 1)
    def score(texts):
        out = []
        for i in range(0, len(texts), 16):
            enc = tok(texts[i:i+16], return_tensors='pt', truncation=True, max_length=256, padding=True)
            with torch.no_grad(): p = torch.softmax(model(**enc).logits, -1)[:, int(ai_idx)]
            out += p.tolist()
        return out
    res[key] = {'ai_label_index': int(ai_idx)}
    for lang in ('en', 'fr'):
        h = score([x['text'] for x in human[lang]]); g = score([x['text'] for x in gen[lang]])
        res[key][lang] = {'human': h, 'generated': g, 'auc': auc(g, h)}
        print(key, lang, 'AUC %.3f' % auc(g, h), flush=True)
json.dump(res, open('scores.json', 'w'))
