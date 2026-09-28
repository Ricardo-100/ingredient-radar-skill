import {AbsoluteFill,CanvasImage,staticFile} from "remotion";
import {Backdrop,Header,Footer,Reveal,Radar,C} from "../ui";
export const CTA=()=> <AbsoluteFill className="video"><Backdrop/><Header index={7} label="GET THE SKILL"/>
<Reveal style={{position:"absolute",left:112,top:232,display:"flex",alignItems:"center",gap:35}}><Radar size={125}/><div style={{fontSize:113,fontWeight:700,letterSpacing:-5}}>成分雷达</div></Reveal>
<Reveal delay={15} style={{position:"absolute",left:112,top:444}}><div style={{fontSize:101,fontWeight:600,letterSpacing:-3,color:C.mint}}>拍清标签，吃得明白。</div></Reveal>
<Reveal delay={34} style={{position:"absolute",left:116,top:642}}>
<div className="eyebrow" style={{marginBottom:18}}>在 GITHUB 获取项目</div>
<div className="mono" style={{fontSize:33,color:C.muted}}>github.com/Ricardo-100/</div>
<div className="mono" style={{fontSize:43,marginTop:10}}>ingredient-radar-skill</div>
</Reveal>
<Reveal delay={48} style={{position:"absolute",right:112,top:596,padding:15,background:C.cream,borderRadius:15}}>
<CanvasImage src={staticFile("repo-qr.png")} style={{width:238,height:238}}/>
</Reveal>
<div style={{position:"absolute",left:116,bottom:157,fontSize:25,color:C.muted}}>配料与营养信息分析 · 结果以原包装为准 · 不替代专业建议</div>
<Footer index={7}/></AbsoluteFill>;