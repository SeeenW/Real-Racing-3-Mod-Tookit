//
//  full_screen_effects.vsh
//
//  Created by bend on 20/07/10.
//  Copyright Firemint 2009. All rights reserved.
//

//%0define PASS_THROUGH

//%1define RADIAL_BLUR

//%2define DEPTH_WRITE

//%3define DEPTH_OF_FIELD

//%4define DEPTH_OF_FIELD
//%4define DEPTH_OF_FIELD_DEBUG_DEPTH

//%5define DEPTH_OF_FIELD
//%5define DEPTH_OF_FIELD_DEBUG_DEPTH_HALF

//%6define DEPTH_OF_FIELD
//%6define DEPTH_OF_FIELD_DEBUG_BLUR

//%7define MOTION_BLUR_ACCUMULATE

//%8define MOTION_BLUR_COMPOSIT

//%9define BLOOM

//%10define BLOOM
//%10define BLOOM_DEBUG

//%11define RADIAL_BLUR
//%11define BLOOM

//%12define DEPTH_OF_FIELD
//%12define BLOOM

//%13define MOTION_BLUR_COMPOSIT
//%13define BLOOM

//%14define COLOR_CURVES

//%15define COLOR_CURVES
//%15define FRAMEBUFFER_FETCH


//////////////////////////////////////////////

//%feature PASS_THROUGH
//%feature RADIAL_BLUR
//%feature DEPTH_WRITE
//%feature DEPTH_OF_FIELD
//%feature DEPTH_OF_FIELD_DEBUG_DEPTH
//%feature DEPTH_OF_FIELD_DEBUG_DEPTH_HALF
//%feature DEPTH_OF_FIELD_DEBUG_BLUR
//%feature MOTION_BLUR_ACCUMULATE
//%feature MOTION_BLUR_COMPOSIT
//%feature BLOOM
//%feature BLOOM_DEBUG
//%feature COLOR_CURVES
//%feature FRAMEBUFFER_FETCH
//%feature MOTION_BLUR_CAMERA
//%feature MOTION_BLUR_CAMERA_WRITE_ALPHA 

//%precompile PASS_THROUGH
//%precompile COLOR_CURVES
//%precompile COLOR_CURVES, FRAMEBUFFER_FETCH

// Simple pass through shader
// ==============================================================
#if defined(PASS_THROUGH) || defined(DEPTH_WRITE) || defined(MOTION_BLUR_CAMERA) || defined(DEPTH_OF_FIELD) || (defined(COLOR_CURVES) && !defined(FRAMEBUFFER_FETCH)) || (defined(BLOOM) && !(defined(RADIAL_BLUR) || defined(MOTION_BLUR_COMPOSIT)))
attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

uniform highp mat4 u_ModelToProj;
varying highp vec2 v_TexCoord;

void main()
{
	v_TexCoord = a_TexCoord0;
	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}
#endif

// Framebuffer fetch extension
// ===========================
#if defined(FRAMEBUFFER_FETCH)
attribute vec3 a_Position;	//%attributeID MT_POS

uniform mat4 u_ModelToProj;

void main()
{
	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}
#endif

// Radial blur shader
// ==============================================================
#if defined(RADIAL_BLUR)
attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

uniform highp mat4 u_ModelToProj;
uniform highp float u_speedFactor;
varying highp vec2 v_TexCoord[5];

void main()
{
	// Direction for radial blur (-1 to 1)
	highp vec2 dir = (a_TexCoord0 * 2.0) - vec2( 1.0 );

	// Resize it to the length of a single pixel (diagonally), and multiply by the speed factor.
	dir *= -vec2( 1.0 / 1024.0, 1.0 / 768.0 ) * u_speedFactor;

	// Radial blur tex coords
	v_TexCoord[0] = a_TexCoord0;
	v_TexCoord[1] = a_TexCoord0 + dir * 4.0;
	v_TexCoord[2] = a_TexCoord0 + dir * 8.0;
	v_TexCoord[3] = a_TexCoord0 + dir * 12.0;
	v_TexCoord[4] = a_TexCoord0 + dir * 16.0;

	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}
#endif

// ==============================================================
#if defined(MOTION_BLUR_ACCUMULATE) || defined(MOTION_BLUR_COMPOSIT)
attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

uniform highp mat4 u_ModelToProj;
uniform highp mat3 u_TexMatrix0;
varying highp vec2 v_TexCoord;

void main()
{
	v_TexCoord = (u_TexMatrix0 * vec3( a_TexCoord0, 1.0 )).xy;
	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}
#endif

