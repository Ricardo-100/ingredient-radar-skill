from pathlib import Path
import sys, json, shutil, asyncio, subprocess, wave
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "promo-video"
PUB = APP / "public"
OUT = ROOT / "output" / "promo-video"
PUB.mkdir(exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "output" / "video-tools"))
import edge_tts
SCENES = [
  {"id":"hook","start":0,"end":6,"text":"包装上写着高蛋白，就一定适合你的目标吗？"},
  {"id":"brand","start":6,"end":12,"text":"成分雷达，把标签里的信息，变成有依据的选择。"},
  {"id":"input","start":12,"end":23,"text":"把照片交给支持看图的智能助手，说明目标和忌口。这里选择减脂控糖，避开花生。"},
  {"id":"numbers","start":23,"end":35,"text":"示例一整包六十克。脚本算出，每份糖十九点四克，热量二百八十千卡。同时保留每百克口径。"},
  {"id":"evidence","start":35,"end":47,"text":"配料表里的花生酱，对应直接含有花生的提示。每条结论都保留原文和定位框，方便回看核对。"},
  {"id":"review","start":47,"end":53,"text":"看不清的数字，明确提示复核。目标，由你决定。"},
  {"id":"cta","start":53,"end":60,"text":"成分雷达。拍清标签，吃得明白。在 GitHub，获取这个技能。"}
]
for src, dest in [
    (ROOT/"samples/sample_wafer.jpg", PUB/"sample-label.jpg"),
    (ROOT/"samples/negative_blurry.jpg", PUB/"blurry-label.jpg"),
    (ROOT/"output/promo-demo/result.jpg", PUB/"actual-result.jpg"),
]:
    shutil.copyfile(src, dest)
data = json.loads((ROOT/"output/promo-demo/contract.json").read_text(encoding="utf-8"))
safe = {k:data[k] for k in ["product","goal_label","serving_g","per_100g","per_serving","allergen_hits","verdict","evidence","disclaimer","rules_version"]}
(APP/"src/demo-data.json").write_text(json.dumps(safe,ensure_ascii=False,indent=2),encoding="utf-8")
import qrcode
qr=qrcode.QRCode(border=2,box_size=10,error_correction=qrcode.constants.ERROR_CORRECT_M)
qr.add_data("https://github.com/Ricardo-100/ingredient-radar-skill"); qr.make(fit=True)
qr.make_image(fill_color="#092B23",back_color="#F4F7EE").save(PUB/"repo-qr.png")
(OUT/"storyboard.json").write_text(json.dumps(SCENES,ensure_ascii=False,indent=2),encoding="utf-8")
async def voice(scene):
    path=OUT/(scene["id"]+".mp3")
    if not path.exists() or path.stat().st_size < 1000:
        await edge_tts.Communicate(scene["text"], "zh-CN-XiaoxiaoNeural",rate="+5%").save(str(path))
    return path
async def main():
    for scene in SCENES:
        path=await voice(scene)
        print("voice", scene["id"], path.stat().st_size,flush=True)
asyncio.run(main())
SR=48000; N=60*SR
voice_mix=np.zeros(N,dtype=np.float32)
timings=[]
for s in SCENES:
    f=OUT/(s["id"]+".mp3")
    duration=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(f)]))
    available=s["end"]-s["start"]-0.85
    speed=max(1.0, duration/available)
    decoded=subprocess.check_output(["ffmpeg","-v","error","-i",str(f),"-af",f"atempo={speed:.6f},loudnorm=I=-17:TP=-2:LRA=7","-ar",str(SR),"-ac","1","-f","f32le","pipe:1"])
    samples=np.frombuffer(decoded,dtype="<f4")
    start=int((s["start"]+0.45)*SR)
    n=min(len(samples),N-start)
    voice_mix[start:start+n]+=samples[:n]
    timings.append({**s,"voice_start":s["start"]+0.45,"voice_duration":n/SR,"speed":speed})
music=np.zeros(N,dtype=np.float32)
rng=np.random.default_rng(13)
def tone(start,duration,freq,gain,kind="pluck"):
    p=int(start*SR); count=min(int(duration*SR),N-p)
    if count<=0:return
    t=np.arange(count)/SR
    if kind=="pluck":
        env=(1-np.exp(-t*120))*np.exp(-t*3.8)
        a=np.sin(2*np.pi*freq*t)+.24*np.sin(2*np.pi*freq*2*t)+.08*np.sin(2*np.pi*freq*3*t)
    elif kind=="bass":
        env=(1-np.exp(-t*70))*np.exp(-t*2.5)
        a=np.sin(2*np.pi*freq*t)
    elif kind=="hat":
        env=np.exp(-t*65); a=rng.normal(0,.23,count)
    elif kind=="kick":
        env=np.exp(-t*15); a=np.sin(2*np.pi*(47*t+5*(1-np.exp(-t*25))))
    music[p:p+count]+=gain*env*a
beat=60/104
chords=[[60,64,67,71],[57,60,64,67],[53,57,60,64],[55,59,62,67]]
for b in range(int(60/beat)+1):
    at=b*beat; chord=chords[(b//8)%4]
    tone(at,1.1,440*2**((chord[b%4]-69)/12),.028)
    tone(at+beat*.5,.6,440*2**((chord[(b+2)%4]+12-69)/12),.012)
    if b%2==0:
        tone(at,.5,440*2**((chord[0]-24-69)/12),.045,"bass")
        tone(at,.18,60,.024,"kick")
    tone(at+.5*beat,.08,0,.018,"hat")
for at in [6,12,23,35,47,53]:
    tone(at,.8,880,.035)
    tone(at+.09,.6,1320,.014)
env=np.minimum(np.arange(N)/SR/1.4,1)*np.minimum((N-np.arange(N))/SR/2.2,1)
duck=np.ones(N,dtype=np.float32)
for t in timings:
    p=int(t["voice_start"]*SR); q=min(N,int((t["voice_start"]+t["voice_duration"])*SR))
    duck[max(0,p-int(.12*SR)):min(N,q+int(.15*SR))]=.45
mixed=voice_mix+music*env*duck
mixed*=min(1,.88/max(.001,np.max(np.abs(mixed))))
stereo=np.stack([mixed,mixed],axis=1)
with wave.open(str(PUB/"soundtrack.wav"),"wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((stereo*32767).astype("<i2").tobytes())
(OUT/"narration-timing.json").write_text(json.dumps(timings,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(timings,ensure_ascii=False),flush=True)
