import {AbsoluteFill,CanvasImage,interpolate,staticFile,useCurrentFrame} from "remotion";
import {Backdrop,Header,Footer,Reveal,SectionTitle,C,clamp} from "../ui";
import data from "../demo-data.json";
export const Numbers=()=>{
const f=useCurrentFrame();
const sugar=interpolate(f,[78,117],[0,data.per_serving.sugar],clamp).toFixed(1);
const kcal=Math.round(interpolate(f,[125,160],[0,data.per_serving.kcal],clamp));
return <AbsoluteFill className="video"><Backdrop/><Header index={4} label="READ → CALCULATE"/><SectionTitle step="操作 02 / 从标签折算到每份">看清你真正吃下的量。</SectionTitle>
<Reveal delay={8} style={{position:"absolute",left:112,top:337,width:586,height:574,background:C.cream,borderRadius:22,padding:14,overflow:"hidden"}}>
<CanvasImage src={staticFile("sample-label.jpg")} style={{width:"100%",height:"100%",objectFit:"contain"}}/>
<div style={{position:"absolute",left:43,top:299,width:503,height:222,border:"3px solid "+C.mint,background:"#BBF88D12",opacity:interpolate(f,[30,45],[0,1],clamp)}}/>
<div style={{position:"absolute",top:interpolate(f,[0,96],[70,516],clamp),left:28,width:530,height:3,background:C.mint,opacity:f<110?.8:0}}/>
</Reveal>
<div style={{position:"absolute",left:802,top:353,width:990}}>
<Reveal delay={23}><div style={{fontSize:31,color:C.muted}}>食用口径 <span style={{color:C.cream,marginLeft:22}}>整包 {data.serving_g} g</span></div><div style={{height:1,background:C.line,marginTop:24}}/></Reveal>
<div style={{display:"flex",gap:90,marginTop:44}}>
<Reveal delay={70}><div style={{fontSize:31,color:C.muted}}>每份糖</div><div style={{fontSize:133,lineHeight:1.25,fontWeight:700,letterSpacing:-7,color:C.orange}}>{sugar}<span style={{fontSize:47,letterSpacing:0,marginLeft:15}}>g</span></div></Reveal>
<Reveal delay={118}><div style={{fontSize:31,color:C.muted}}>每份热量</div><div style={{fontSize:133,lineHeight:1.25,fontWeight:700,letterSpacing:-7}}>{kcal}<span style={{fontSize:36,letterSpacing:0,marginLeft:14}}>kcal</span></div></Reveal>
</div>
<Reveal delay={172}><div style={{marginTop:30,padding:"23px 28px",border:"1px solid #365440",borderRadius:13,fontSize:30,color:C.muted}}>每 100 g：糖 {data.per_100g.sugar} g · 热量 {data.per_100g.kcal} kcal</div></Reveal>
<Reveal delay={224}><div style={{marginTop:25,display:"flex",alignItems:"center",gap:17,fontSize:34,color:C.mint}}><span style={{fontSize:48}}>↳</span>双口径保留，份量由你指定。</div></Reveal>
</div>
<div style={{position:"absolute",left:116,top:923,fontSize:20,color:C.muted}}>仓库样例回放 · 数值来自实际脚本输出</div>
<Footer index={4}/></AbsoluteFill>
};