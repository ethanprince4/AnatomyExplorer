# Contrast of every gauge colour against the wall behind the gauge (y = 232, the lightest point it covers), per scheme.
#   python app/specimen-gauge/contrast.py     prints the lowest value of each part over the six walls
import json, os
s=open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'system', 'schemes.js')).read()
J=json.loads(s[s.index('{'):s.rindex('}')+1])['specimen']['schemes']
h=lambda c:[int(c[i:i+2],16)/255 for i in (1,3,5)]
def L(c):
    r=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in c]; return .2126*r[0]+.7152*r[1]+.0722*r[2]
cr=lambda a,b:(max(L(a),L(b))+.05)/(min(L(a),L(b))+.05)
mix=lambda a,b,t:[a[i]*t+b[i]*(1-t) for i in range(3)]
worst={}
for k,v in J.items():
    wall=mix(h(v['stage_bottom']),h(v['stage_top']),232/1080); spot=h(v['spot'])
    band=mix(h(v['text']),wall,.05)
    parts={  # name: (colour, background, minimum)
      'rail/ticks/band lines (leader)':(h(v['leader']),wall,3),'fine marks, past band lines (text-3 70%)':(mix(h(v['text_3']),wall,.7),wall,3),
      'brass fill and knob':(h(v['accent']),wall,3),'knob on lit band':(h(v['accent']),spot,3),'focus ring (text)':(h(v['text']),wall,3),
      'B3 rail (text-3 70%)':(mix(h(v['text_3']),wall,.7),wall,3),'checkbox edge (text-2)':(h(v['text_2']),wall,3),
      'B2 band line vs band fill':(h(v['leader']),band,3),
      'past names, end labels (text-3)':(h(v['text_3']),wall,4.5),'names to come (text-2)':(h(v['text_2']),wall,4.5),
      'current name (text)':(h(v['text']),wall,4.5),'percentage (accent-2)':(h(v['accent_2']),wall,4.5),'toggle text (text-2)':(h(v['text_2']),wall,4.5)}
    for n,(a,b,m) in parts.items():
        c=cr(a,b)
        if n not in worst or c<worst[n][0]: worst[n]=(c,k,m)
for n,(c,k,m) in worst.items(): print(f'{n:45s} lowest {c:5.2f}:1 ({k})  need {m}:1  {"ok" if c>=m else "FAIL"}')
