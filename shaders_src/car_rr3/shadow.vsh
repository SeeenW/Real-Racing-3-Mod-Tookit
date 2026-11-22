//
//  shadow.vsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

//%0define USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
//%1define USE_SHADOW_MAP
//%2define DISABLE_CUBE_MAP

////////////////////////////////////////////////

//%feature USE_SHADOW_MAP

//%precompile USE_SHADOW_MAP
//%precompile

const highp float c_zero = 0.0;
const highp float c_one = 1.0;

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute mediump vec2 a_TexCoord0;	//%attributeID MT_UV_0		Diffuse UV channel
attribute highp vec3 a_Colour;		//%attributeID MT_COLOUR

// Uniforms
// ----------------------------------------------------------------------

// Fog
uniform highp float u_FogStart;
uniform lowp float u_FogFactor;
uniform lowp float u_FogSaturation;

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

// ======================================================================
// Outputs
// ======================================================================

varying mediump vec2 v_TexCoord0;
varying lowp float v_FogFactor;
varying lowp vec3 v_VertColor;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

#ifdef USE_SHADOW_MAP
	uniform highp mat4 u_ModelToShadow;
	varying lowp vec2 v_ShadowUV;
#endif

void main()
{
	v_TexCoord0 = a_TexCoord0 * uvMult;

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

	// Fog is already applied to the ground pixels, so applying it again will never be correct. Shadow should be
	// modulated in before blending with the fog. Best we can do is reduce the strength of shadow based on fog
	// distance if we don't want to use a multi-pass approach. Make the fog factor 2x stronger to make up for the
	// fact that shadow will be modulating the fog part already present in the dst color.

	v_FogFactor = 1.0 - clamp( (pos.w - u_FogStart) * u_FogFactor * 2.0, c_zero, u_FogSaturation );

#ifdef USE_SHADOW_MAP
	v_ShadowUV = (u_ModelToShadow * vec4( a_Position, c_one )).xz;
#endif

	v_VertColor = a_Colour.rgb;
	gl_Position = pos;
}

