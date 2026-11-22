//
//  checker_pattern.vsh
//
//  Created by bend on 15/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

//%precompile

// Inputs
// -----------------------------------
attribute vec4 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

uniform highp mat4 u_ModelToProj;

// Outputs
// -----------------------------------
varying highp vec2 v_TexCoord0;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	v_TexCoord0 = a_TexCoord0 * uvMult;
	gl_Position = u_ModelToProj * a_Position;
}

