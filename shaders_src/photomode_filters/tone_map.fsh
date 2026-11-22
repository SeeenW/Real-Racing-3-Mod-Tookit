//
//  black_and_white.vsh
//
//  Created by bend on 06/09/13.
//  Copyright EA 2013. All rights reserved.
//

// Use EXT_shader_framebuffer_fetch extension if available
//
//   Defines FRAMEBUFFER_RGBA as the source fragment colour
//

#ifdef FRAMEBUFFER_FETCH
	#extension GL_EXT_shader_framebuffer_fetch : require
	#define FRAMEBUFFER_RGBA gl_LastFragData[0]
#else
	uniform lowp sampler2D s_Texture0;		// Screen texture
	varying lowp vec2 v_TexCoord;
	#define FRAMEBUFFER_RGBA texture2D(s_Texture0, v_TexCoord)
#endif

uniform lowp sampler2D s_Texture1;			// Tone map texture

const mediump float CURVE_COUNT = 15.0;
uniform mediump float mu_CurveRow;

void main()
{
	lowp float rowPos = 1.0 - ((mu_CurveRow + 0.5) / CURVE_COUNT);
	lowp vec3 colour = FRAMEBUFFER_RGBA.rgb;
	lowp float r = texture2D( s_Texture1, vec2( clamp( colour.r, 0.004, 0.996 ), rowPos ) ).r;
	lowp float g = texture2D( s_Texture1, vec2( clamp( colour.g, 0.004, 0.996 ), rowPos ) ).g;
	lowp float b = texture2D( s_Texture1, vec2( clamp( colour.b, 0.004, 0.996 ), rowPos ) ).b;

	//const lowp vec3 vignetteColor = vec3( 0.0, 0.0, 0.0 );
	//const lowp vec2 vignetteCenter = vec2( 0.5, 0.5 );
	//const lowp float vignetteStart = 0.4;
	//const lowp float vignetteEnd = 0.75;
	//
	//lowp float d = distance( v_TexCoord, vignetteCenter );
	//lowp float percent = smoothstep( vignetteStart, vignetteEnd, d );
	//
	//gl_FragColor = vec4( mix( r, vignetteColor.r, percent ),
	//					 mix( g, vignetteColor.g, percent ),
	//					 mix( b, vignetteColor.b, percent ),
	//					 1.0 );

	gl_FragColor = vec4( r, g, b, 1.0 );
}

