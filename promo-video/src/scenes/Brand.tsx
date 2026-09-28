import {AbsoluteFill,interpolate,useCurrentFrame} from "remotion";
import {Backdrop,Header,Footer,Reveal,Radar,C,clamp} from "../ui";
export const Brand=()=>{const f=useCurrentFrame();return <AbsoluteFill className="video"><Backdrop/><Header index={2} label="MEET YOUR SKILL"/>
<div style={{position:"absolute",left:112,top:270,display:"flex",gap:60,alignItems:"center"}}>
<Reveal><div style={{scale:interpolate(f,[0,35],[.75,1],clamp)}}><Radar size={245}/></div></Reveal>
<Reveal delay={7}><div className="eyebrow" style={{marginBottom:10}}>食品标签分析 SKILL</div><div style={{fontSize:176,fontWeight:700,letterSpacing:-9,lineHeight:1.1}}>成分雷达<span style={{color:C.mint}}>。</span></div></Reveal>
</div>
<Reveal delay={23} style={{position:"absolute",left:420,top:610}}><div style={{fontSize:57,fontWeight:500}}>让每一次选择，都有依据。</div></Reveal>
<div style={{position:"absolute",left:420,top:740,display:"flex",gap:66}}>{["一张标签","你的目标","原图证据"].map((s,i)=><Reveal key={s} delay={35+i*9}><div style={{display:"flex",alignItems:"center",gap:18,fontSize:31,color:C.muted}}><span className="mono" style={{color:C.mint}}>0{i+1}</span>{s}</div></Reveal>)}</div>
<Footer index={2}/></AbsoluteFill>};