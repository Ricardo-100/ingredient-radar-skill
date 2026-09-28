import React from "react";
import {AbsoluteFill,Easing,interpolate,useCurrentFrame} from "remotion";
export const C={bg:"#081F18",mint:"#BBF88D",cream:"#F4F6ED",ink:"#123D2E",muted:"#AEC4B7",orange:"#FFB196",line:"#31513D"};
export const clamp={extrapolateLeft:"clamp",extrapolateRight:"clamp"} as const;
export const ease=Easing.bezier(.16,1,.3,1);
export const Reveal:React.FC<{children:React.ReactNode;delay?:number;style?:React.CSSProperties}>=({children,delay=0,style})=>{
 const f=useCurrentFrame();
 return <div style={{opacity:interpolate(f,[delay,delay+18],[0,1],clamp),translate:"0px "+interpolate(f,[delay,delay+26],[34,0],{...clamp,easing:ease})+"px",...style}}>{children}</div>;
};
export const Radar:React.FC<{size?:number;light?:boolean;rate?:number}>=({size=90,light=false,rate=1})=>{
 const f=useCurrentFrame();const stroke=light?C.ink:C.mint;
 return <svg width={size} height={size} viewBox="0 0 100 100" style={{overflow:"visible"}}>
 <circle cx="50" cy="50" r="46" fill="none" stroke={stroke} strokeWidth="2" opacity=".55"/>
 <circle cx="50" cy="50" r="30" fill="none" stroke={stroke} strokeWidth="1" opacity=".35"/>
 <circle cx="50" cy="50" r="14" fill="none" stroke={stroke} strokeWidth="1" opacity=".22"/>
 <path d="M4 50H96M50 4V96" stroke={stroke} opacity=".17"/>
 <g style={{transformOrigin:"50px 50px",rotate:(f*rate-55)+"deg"}}>
 <path d="M50 50L50 4A46 46 0 0 1 90 27Z" fill={stroke} opacity=".13"/>
 <path d="M50 50L50 4" stroke={stroke} strokeWidth="2"/>
 </g><circle cx="73" cy="31" r="4" fill={stroke}/><circle cx="36" cy="67" r="3" fill={stroke}/>
 <circle cx="50" cy="50" r="5" fill={stroke}/></svg>;
};
export const Backdrop:React.FC<{light?:boolean}>=({light=false})=>{
 const f=useCurrentFrame();const color=light?C.ink:C.mint;
 return <AbsoluteFill style={{background:light?C.cream:C.bg,overflow:"hidden"}}>
 <div style={{position:"absolute",inset:0,background:light?"radial-gradient(circle at 80% 45%,#E0EACD 0,transparent 55%)":"radial-gradient(circle at 84% 18%,#204C35 0,transparent 52%)"}}/>
 <div style={{position:"absolute",inset:0,opacity:light?.055:.08,backgroundImage:"linear-gradient("+color+" 1px,transparent 1px),linear-gradient(90deg,"+color+" 1px,transparent 1px)",backgroundSize:"80px 80px",maskImage:"linear-gradient(90deg,transparent 10%,black 100%)"}}/>
 <div style={{position:"absolute",right:-200,top:-290,opacity:light?.1:.09,rotate:(f*.018)+"deg"}}><Radar size={1100} light={light} rate={.25}/></div>
 </AbsoluteFill>;
};
export const Header:React.FC<{index:number;label?:string;light?:boolean}>=({index,label="INGREDIENT RADAR",light=false})=><div style={{position:"absolute",left:112,right:112,top:55,display:"flex",alignItems:"center",justifyContent:"space-between",color:light?C.ink:C.cream}}>
 <div style={{display:"flex",alignItems:"center",gap:17}}><Radar size={43} light={light}/><span style={{fontSize:29,fontWeight:600}}>成分雷达</span><span className="mono" style={{fontSize:16,opacity:.55,marginLeft:12}}>INGREDIENT RADAR</span></div>
 <div className="mono" style={{fontSize:21,opacity:.68}}>{label}<span style={{marginLeft:34}}>{String(index).padStart(2,"0")} / 07</span></div>
 </div>;
export const Chip:React.FC<{children:React.ReactNode;active?:boolean;warm?:boolean;style?:React.CSSProperties}>=({children,active=false,warm=false,style})=><div style={{display:"inline-flex",alignItems:"center",padding:"15px 25px",borderRadius:12,border:"1px solid "+(active?C.mint:"#56705B"),background:active?C.mint:warm?"#533A2F":"transparent",color:active?C.ink:warm?C.orange:C.cream,fontSize:32,fontWeight:600,...style}}>{children}</div>;
export const SectionTitle:React.FC<{step:string;children:React.ReactNode;light?:boolean}>=({step,children,light=false})=><div style={{position:"absolute",left:112,top:154,color:light?C.ink:C.cream}}><div className="eyebrow" style={{marginBottom:18,color:light?"#607964":undefined}}>{step}</div><h2 className="title">{children}</h2></div>;
export const Arrow:React.FC<{color?:string;width?:number}>=({color=C.mint,width=100})=><svg width={width} height="50" viewBox="0 0 100 50"><path d="M3 25H92M73 7L94 25L73 43" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round"/></svg>;
export const Check:React.FC<{size?:number;color?:string}>=({size=28,color=C.mint})=><svg width={size} height={size} viewBox="0 0 24 24"><path d="M4 12L9 17L20 6" fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg>;
export const Footer:React.FC<{index:number;light?:boolean}>=({index,light=false})=><div style={{position:"absolute",left:112,right:112,bottom:33,display:"flex",gap:10}}>{Array.from({length:7},(_,i)=><div key={i} style={{height:3,flex:1,background:i+1===index?(light?C.ink:C.mint):(light?"#C5D3C3":"#2D4838")}}/>)}</div>;
