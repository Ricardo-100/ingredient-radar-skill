import {AbsoluteFill,CanvasImage,interpolate,staticFile,useCurrentFrame} from "remotion";
import {Backdrop,Header,Footer,Reveal,SectionTitle,Arrow,C,clamp} from "../ui";
export const Evidence=()=>{const f=useCurrentFrame();return <AbsoluteFill className="video"><Backdrop/><Header index={5} label="EVIDENCE MATTERS"/><SectionTitle step="操作 03 / 回看依据">每条判断，都有出处。</SectionTitle>
<Reveal delay={6} style={{position:"absolute",left:112,top:335,width:590,height:590,borderRadius:17,overflow:"hidden",border:"1px solid #6A8268"}}>
<CanvasImage src={staticFile("actual-result.jpg")} style={{width:"100%",height:"100%",objectFit:"contain",background:"#202B29"}}/>
<div style={{position:"absolute",right:14,top:15,background:C.mint,color:C.ink,fontSize:20,borderRadius:6,padding:"8px 14px"}}>真实脚本结果图</div>
</Reveal>
<div style={{position:"absolute",left:737,top:538,opacity:interpolate(f,[45,63],[0,1],clamp)}}><Arrow width={74}/></div>
<div style={{position:"absolute",left:856,top:338,width:952}}>
<Reveal delay={30}><div style={{fontSize:28,color:C.muted,marginBottom:18}}>原文证据 / 配料表</div>
<div style={{height:130,background:C.cream,color:C.ink,borderRadius:14,overflow:"hidden",position:"relative"}}>
<CanvasImage src={staticFile("sample-label.jpg")} style={{position:"absolute",width:1250,height:1250,left:-43,top:-280}}/>
<div style={{position:"absolute",left:19,top:37,width:161,height:57,border:"3px solid #39915B",background:"#BBF88D25"}}/>
</div></Reveal>
<Reveal delay={89}><div style={{marginTop:32,color:C.orange,fontSize:54,fontWeight:600}}>命中花生 · 直接含有</div><div style={{marginTop:15,color:C.muted,fontSize:30}}>匹配你明确提供的过敏忌口</div></Reveal>
<Reveal delay={155}><div className="panel" style={{marginTop:35,padding:"22px 28px",display:"flex",justifyContent:"space-between",alignItems:"center"}}><span style={{fontSize:30}}>本例：减脂 · 控糖</span><span style={{fontSize:38,color:C.orange,fontWeight:600}}>不推荐</span></div></Reveal>
<Reveal delay={228}><div style={{marginTop:26,fontSize:31,color:C.mint}}>原文 + 定位框，方便逐条核对。</div></Reveal>
</div><Footer index={5}/></AbsoluteFill>};