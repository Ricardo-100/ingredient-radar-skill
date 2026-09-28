import {AbsoluteFill,CanvasImage,interpolate,staticFile,useCurrentFrame} from "remotion";
import {Backdrop,Header,Footer,Reveal,SectionTitle,Chip,Check,C,clamp} from "../ui";
export const Input=()=>{
const f=useCurrentFrame();const goal=f>136,allergy=f>193;
const message="请用成分雷达分析这张标签。\n目标：减脂控糖\n过敏忌口：花生\n一次食用：整包 60 g";
const typed=message.slice(0,Math.floor(interpolate(f,[45,125],[0,message.length],clamp)));
return <AbsoluteFill className="video"><Backdrop/><Header index={3} label="WORKFLOW DEMO"/><SectionTitle step="操作 01 / 提供照片与目标">把问题，说清楚。</SectionTitle>
<Reveal delay={8} style={{position:"absolute",left:112,top:384,width:600}}>
<div style={{fontSize:31,color:C.muted,marginBottom:22}}>先选择你的目标</div>
<div style={{display:"flex",gap:13,flexWrap:"wrap"}}><Chip style={{fontSize:26}}>增肌</Chip><Chip active={goal} style={{fontSize:26}}>减脂 · 控糖 {goal&&"✓"}</Chip><Chip style={{fontSize:26}}>生酮</Chip></div>
<div style={{fontSize:31,color:C.muted,marginTop:52,marginBottom:22}}>再明确过敏与忌口</div>
<Chip warm={allergy} style={{borderColor:allergy?C.orange:undefined}}>花生 {allergy&&"✓"}</Chip>
<Reveal delay={238} style={{marginTop:50,fontSize:30,lineHeight:1.7,color:C.mint}}>照片 + 目标 + 忌口<br/>交给支持看图的 Agent</Reveal>
</Reveal>
<Reveal delay={14} style={{position:"absolute",left:810,top:336,width:998,height:561,borderRadius:24,background:C.cream,color:C.ink,boxShadow:"0 26px 65px #0005",overflow:"hidden"}}>
<div style={{height:70,padding:"0 32px",borderBottom:"1px solid #DBE3D8",display:"flex",alignItems:"center",justifyContent:"space-between",fontSize:24}}><span>Agent 对话</span><span style={{fontSize:20,color:"#718572"}}>对话流程示意 · 非独立 App</span></div>
<div style={{padding:32,display:"flex",gap:30}}>
<div><CanvasImage src={staticFile("sample-label.jpg")} style={{width:270,height:270,borderRadius:10}}/><div style={{fontSize:18,color:"#6D7D6F",marginTop:12}}>sample_wafer.jpg · 仓库样例</div></div>
<div style={{flex:1,background:"#E3ECD8",borderRadius:18,padding:"26px 28px",fontSize:29,whiteSpace:"pre-line",lineHeight:1.75,minHeight:268}}>{typed}<span style={{opacity:f<125?1:0}}>▏</span></div>
</div>
<Reveal delay={250} style={{margin:"0 32px",borderTop:"1px solid #D4DFCF",paddingTop:17,display:"flex",gap:14,alignItems:"center",fontSize:25}}><Check color={C.ink}/><span>读取标签字段，按你的目标分析。</span></Reveal>
</Reveal>
{f>130&&f<160&&<div style={{position:"absolute",left:391,top:495,width:52,height:52,borderRadius:"50%",border:"2px solid "+C.mint,scale:interpolate(f,[131,158],[.3,1.9],clamp),opacity:interpolate(f,[143,160],[1,0],clamp)}}/>}
<Footer index={3}/></AbsoluteFill>
};