from pathlib import Path
import json,re
root=Path(__file__).resolve().parents[2]
timings=json.loads((root/"output/promo-video/narration-timing.json").read_text(encoding="utf-8"))
caps=[]
for s in timings:
    chunks=[p.strip() for p in re.split(r"[，。？]",s["text"]) if p.strip()]
    weights=[len(x)+2 for x in chunks]
    duration=max(.2,s["voice_duration"]-.15)
    now=s["voice_start"]
    for part,w in zip(chunks,weights):
        end=now+duration*w/sum(weights)
        caps.append({"start":round(now,3),"end":round(end,3),"text":part})
        now=end
(root/"promo-video/src/captions.json").write_text(json.dumps(caps,ensure_ascii=False,indent=2),encoding="utf-8")
def tc(t):
    ms=round(t*1000);return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
srt="\n\n".join(f"{i+1}\n{tc(c['start'])} --> {tc(c['end'])}\n{c['text']}" for i,c in enumerate(caps))
(root/"output/promo-video/ingredient-radar-promo.srt").write_text(srt+"\n",encoding="utf-8")
print("captions",len(caps))
