//
//  dof_discard.vsh
//
//  Created by bend on 09/01/14.
//  Copyright EA 2014. All rights reserved.
//

//%precompile

const highp float c_zero = 0.0;
const highp float c_one = 1.0;

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0		Diffuse UV channel

uniform highp mat4 u_ModelToProj;

varying mediump vec2 v_TexCoord0;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	v_TexCoord0 = a_TexCoord0 * uvMult;
	gl_Position = u_ModelToProj * vec4( a_Position, c_one );
}

