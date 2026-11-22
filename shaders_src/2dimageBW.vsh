//
//  2Dimage.vsh
//
//  Created by bend on 27/11/09.
//  Copyright Firemint 2009. All rights reserved.
//

//%precompile

const float c_zero = 0.0;
const float c_one = 1.0;

// Inputs
// -----------------------------------
attribute vec3 a_Position;	//%attributeID MT_POS

uniform highp mat4 u_ModelToProj;

attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0
uniform highp mat3 u_TexMatrix0;
// Outputs
// -----------------------------------
varying mediump vec2 v_TexCoord0;

void main()
{
	v_TexCoord0 = (u_TexMatrix0 * vec3( a_TexCoord0, c_one )).xy;
	gl_Position = u_ModelToProj * vec4( a_Position, c_one );
}

