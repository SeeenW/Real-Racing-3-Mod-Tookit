//
//  diffuse_no_lighting.vsh
//
//  Created by ianu on 27/10/10 from basic_no_lighting.vsh
//  Copyright Firemint 2009. All rights reserved.
//

//%0define NO_SOFT_PARTICLES
//%1define PARTICLE_SOFT_FADE

///////////////////////////////

//%feature PARTICLE_SOFT_FADE
//%precompile

const float c_zero = 0.0;
const float c_one = 1.0;

attribute vec2 a_TexCoord0;		//%attributeID MT_UV_0
varying mediump vec2 v_TexCoord0;

#ifdef PARTICLE_SOFT_FADE
attribute vec2 a_TexCoord2;			//%attributeID MT_UV_2
varying highp vec2 v_TexCoord2;
#endif

// Inputs
// -----------------------------------

// Vertex attributes
// Note: pos.w holds soft fade scale
attribute vec3 a_Position;		//%attributeID MT_POS
attribute vec4 a_Colour;		//%attributeID MT_COLOUR

// Transformation Matrices
uniform highp mat4 u_ModelToProj;
uniform highp mat4 u_ModelToView;
uniform lowp vec3 u_FogColour;

// Fog
uniform mediump float u_FogStart;
uniform mediump float u_FogFactor;
uniform mediump float u_FogSaturation;
varying lowp vec4 v_FogColor;

varying highp vec4 v_VertexColor;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	v_TexCoord0 = a_TexCoord0 * uvMult;

#if defined(PARTICLE_SOFT_FADE)
	v_TexCoord2 = a_TexCoord2 * uvMult;
#endif

	gl_Position = u_ModelToProj * vec4( a_Position, c_one );

	// Fog
	mediump float fogAlpha = clamp((gl_Position.w - u_FogStart) * u_FogFactor, c_zero, u_FogSaturation);
	
	v_FogColor = vec4(u_FogColour * fogAlpha, 1.0 - fogAlpha);

	v_VertexColor = a_Colour;
}
