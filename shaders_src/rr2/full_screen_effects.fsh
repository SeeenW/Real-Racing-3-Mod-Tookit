//
//  full_screen_effects.fsh
//
//  Created by bend on 20/07/10.
//  Copyright Firemint 2009. All rights reserved.
//

// ==============================================================

#ifdef PASS_THROUGH
uniform lowp sampler2D s_Texture0;
varying highp vec2 v_TexCoord;

void main()
{
	gl_FragColor = texture2D( s_Texture0, v_TexCoord );
}
#endif

// ==============================================================
#ifdef RADIAL_BLUR
uniform lowp sampler2D s_Texture0;		// Screen texture

varying highp vec2 v_TexCoord[5];

#ifdef BLOOM
	uniform lowp sampler2D s_Texture1;		// Down sampled screen texture 0 (half dimensions)
	uniform lowp sampler2D s_Texture2;		// Down sampled screen texture 1 (quarter dimensions)
	uniform lowp sampler2D s_Texture3;		// Down sampled screen texture 2 (eighth dimensions)
	
	uniform lowp float u_bloomHalfFactor;
	uniform lowp float u_bloomQuarterFactor;
	uniform lowp float u_bloomEighthFactor;

	uniform lowp vec3 u_bloomTintColor;
#endif

const highp float f1 = 0.35;
const highp float f2 = 0.3;
const highp float f3 = 0.2;
const highp float f4 = 0.1;
const highp float f5 = 0.05;

void main()
{
	lowp vec3 c0 = texture2D( s_Texture0, v_TexCoord[0] ).rgb;
	lowp vec3 c1 = texture2D( s_Texture0, v_TexCoord[1] ).rgb;
	lowp vec3 c2 = texture2D( s_Texture0, v_TexCoord[2] ).rgb;
	lowp vec3 c3 = texture2D( s_Texture0, v_TexCoord[3] ).rgb;
	lowp vec3 c4 = texture2D( s_Texture0, v_TexCoord[4] ).rgb;

#ifdef BLOOM
//	lowp vec3 d1 = texture2D( s_Texture1, v_TexCoord[0] ).rgb;
//	lowp vec3 d2 = texture2D( s_Texture2, v_TexCoord[0] ).rgb;
	// 3x3 gaussian over the 1/8-res bloom layer (the stock code does one
	// bilinear tap, which leaves a blocky halo)
	highp vec2 btex = fwidth( v_TexCoord[0] ) * 8.0;
	highp vec3 d3 = texture2D( s_Texture3, v_TexCoord[0] ).rgb * 0.25;
	d3 += texture2D( s_Texture3, v_TexCoord[0] + vec2( btex.x, 0.0 ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord[0] - vec2( btex.x, 0.0 ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord[0] + vec2( 0.0, btex.y ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord[0] - vec2( 0.0, btex.y ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord[0] + btex ).rgb * 0.0625;
	d3 += texture2D( s_Texture3, v_TexCoord[0] - btex ).rgb * 0.0625;
	d3 += texture2D( s_Texture3, v_TexCoord[0] + vec2( btex.x, -btex.y ) ).rgb * 0.0625;
	d3 += texture2D( s_Texture3, v_TexCoord[0] + vec2( -btex.x, btex.y ) ).rgb * 0.0625;

	d3 = d3 * d3 * d3;
#endif

	lowp vec4 color = vec4(c0 * f1
						 + c1 * f2
						 + c2 * f3
						 + c3 * f4
						 + c4 * f5
#ifdef BLOOM
						+ (
//						 d1 * u_bloomHalfFactor
//						 + d2 * u_bloomQuarterFactor
						 d3 * u_bloomEighthFactor
						 ) * u_bloomTintColor
#endif
						 , 1.0 );

	gl_FragColor = color;
	//gl_FragColor = vec4(u_RedScale, u_GreenScale, u_BlueScale, 1.0);
}
#endif

// ==============================================================
#ifdef DEPTH_WRITE
uniform lowp sampler2D s_Texture0;		// Screen texture
uniform highp sampler2D s_Texture1;		// Depth texture

// Clip info
uniform highp float u_FarClip;
uniform highp float u_NearTimesFar;
uniform highp float u_FarMinusNear;

// Camera info
uniform highp float u_FocalPointInv;
uniform highp float u_ScreenDist;
uniform highp float u_CamAperture;

varying highp vec2 v_TexCoord;

// Transforms the depth value from a normalised depth to the depth
// in world coords.
highp float linearizeDepth( highp float z )
{
	// Formula:
	// (near * far) / (far - (z * (far - near)))
	return u_NearTimesFar / (u_FarClip - (z * u_FarMinusNear));
}

// Transforms the world depth value into focus value.
lowp float focus( highp float z )
{
	// Calculate the circle of confusion
	return abs( u_CamAperture * (u_ScreenDist * (u_FocalPointInv - ((u_FarClip - (z * u_FarMinusNear)) / u_NearTimesFar)) - 1.0) );
}

void main()
{
	lowp vec3 c = texture2D( s_Texture0, v_TexCoord ).rgb;
	highp float z = texture2D( s_Texture1, v_TexCoord ).r;
	gl_FragColor = vec4( c, focus( z ) );
}
#endif


#if defined (MOTION_BLUR_CAMERA) 
uniform highp mat4			u_PreviousViewProj;
uniform highp mat4			u_ViewProjInv;
uniform mediump vec2		u_CameraMotionBlurParams;
uniform mediump vec3 		u_Brightness;
uniform mediump vec3 		u_Contrast;

uniform lowp 	sampler2D 	s_Texture0;		// Screen (Stencil in alpha) 
uniform lowp 	sampler2D  	s_Texture1;		// Depth buffer
varying highp 	vec2 		v_TexCoord;

void main(void)
{
#if defined (MOTION_BLUR_CAMERA_WRITE_ALPHA)
	gl_FragColor = vec4(1.0,1.0,1.0,1.0);
#else
	lowp vec4 c = texture2D( s_Texture0, v_TexCoord);
	highp float z = texture2D(s_Texture1, v_TexCoord).x;
	mediump float blurStrength = u_CameraMotionBlurParams.x;
	mediump float blurZDiscard = u_CameraMotionBlurParams.y;

	highp vec4 ndc = vec4(v_TexCoord * 2.0 - 1.0, z * 2.0 - 1.0, 1.0);

	highp vec4 d = u_ViewProjInv * ndc;
	highp vec4 currentPos = d / d.w;

	highp vec4 prevPos = u_PreviousViewProj * currentPos;
	prevPos = prevPos / prevPos.w;

	highp vec2 vel = (prevPos.xy - ndc.xy) * blurStrength;
	highp vec2 halfVel = vel * 0.5;
	
   	highp vec3 blurColor = vec3(0.0,0.0,0.0);
	highp float samplesTaken = 0.0;

	lowp int sampleCount = 64;
	lowp float sampleCountInv = 1.0 / float(sampleCount);

	for (int i = 0; i < sampleCount; ++i) 
	{
		highp float t = float(i) * sampleCountInv; 
		mediump vec2 sampleTc = v_TexCoord - halfVel + vel * t;
		lowp vec4 sample = texture2D( s_Texture0, sampleTc);
		blurColor  += sample.rgb * sample.a;
		samplesTaken += sample.a;
	}


	if ( samplesTaken  > 0.0 )
	{
		blurColor /= samplesTaken;
		c = vec4(mix(c.rgb, blurColor, c.a), 1.0);
	}
	else
	{
		c = vec4(c.rgb, 1.0);
	}

	// Colour curves
	c.rgb = (c.rgb - 0.5) * u_Contrast + 0.5;
	c.rgb *= u_Brightness;

	gl_FragColor = vec4(c.rgb, 1.0);
#endif
}

#endif

// ==============================================================
#ifdef DEPTH_OF_FIELD

uniform lowp sampler2D s_Texture0;		// Normal screen texture
uniform lowp sampler2D s_Texture1;		// Down sampled screen texture 0 (half dimension), alpha channel has depth value
uniform lowp sampler2D s_Texture2;		// Down sampled screen texture 1 (quarter dimension)
uniform lowp sampler2D s_Texture3;		// Down sampled screen texture 2 (eight dimension)

varying lowp vec2 v_TexCoord;

uniform lowp float u_dofHalfBlurFactor;
uniform lowp float u_dofQuarterBlurFactor;
uniform lowp float u_dofEighthBlurFactor;

#ifdef BLOOM
	uniform lowp float u_bloomHalfFactor;
	uniform lowp float u_bloomQuarterFactor;
	uniform lowp float u_bloomEighthFactor;

	uniform lowp vec3 u_bloomTintColor;
#endif

void main()
{
	lowp vec3 c = texture2D( s_Texture0, v_TexCoord ).rgb;
	lowp vec4 d1a = texture2D( s_Texture1, v_TexCoord );
	lowp vec3 d1 = d1a.rgb;
	lowp vec4 d2a = texture2D( s_Texture2, v_TexCoord );
	lowp vec3 d2 = d2a.rgb;
	lowp vec4 d3a = texture2D( s_Texture3, v_TexCoord );
	lowp vec3 d3 = d3a.rgb;
	lowp float alpha = d1a.a;

#ifdef BLOOM
//	lowp vec3 b1 = d1.rgb * d1.rgb * d1.rgb;
//	lowp vec3 b2 = d2.rgb * d2.rgb * d2.rgb;
	lowp vec3 b3 = d3 * d3 * d3;
#endif

	#if defined(DEPTH_OF_FIELD_DEBUG_DEPTH)
		gl_FragColor = vec4( alpha, alpha, alpha, 1.0 );
	#else
	#if defined(DEPTH_OF_FIELD_DEBUG_DEPTH_HALF)
		if( v_TexCoord.s < 0.5 )
		{
			gl_FragColor = vec4( alpha, alpha, alpha, 1.0 );
		}
		else
		{
			gl_FragColor = vec4( mix( c,
									  d1 * u_dofHalfBlurFactor +
									  d2 * u_dofQuarterBlurFactor +
									  d3 * u_dofEighthBlurFactor,
									  alpha )
								 , 1.0 );
		}
	#else
	#if defined(DEPTH_OF_FIELD_DEBUG_BLUR)
		gl_FragColor = vec4( d1 * u_dofHalfBlurFactor +
							 d2 * u_dofQuarterBlurFactor +
							 d3 * u_dofEighthBlurFactor,
							 1.0 );
	#else
		gl_FragColor = vec4( mix( c,
								  d1 * u_dofHalfBlurFactor +
								  d2 * u_dofQuarterBlurFactor +
								  d3 * u_dofEighthBlurFactor,
								  alpha )
//		gl_FragColor = vec4( c 
		#ifdef BLOOM
							 + (
//							 b1 * u_bloomHalfFactor
//							 + b2 * u_bloomQuarterFactor
							 b3 * u_bloomEighthFactor
							 ) * u_bloomTintColor
		#endif
							 , 1.0 );
	#endif
	#endif //IvanL: I know this is stupid, but unfortunately #elif does not compile on Mali GPU (e.g. Galaxy S3)
	#endif
	//gl_FragColor = vec4( d1a.a, d2a.a, d3a.a, 1.0 );
}
#endif

// ==============================================================
#ifdef MOTION_BLUR_ACCUMULATE
uniform lowp sampler2D s_Texture0;
varying highp vec2 v_TexCoord;

uniform lowp float u_BlurAccumulation;

void main()
{
	gl_FragColor = vec4( texture2D( s_Texture0, v_TexCoord ).rgb, u_BlurAccumulation );
}
#endif

// ==============================================================
#ifdef MOTION_BLUR_COMPOSIT
uniform lowp sampler2D s_Texture0;		// Motion blurred texture
varying highp vec2 v_TexCoord;

void main()
{
	gl_FragColor = texture2D( s_Texture0, v_TexCoord );
}
#endif

// ==============================================================
#if defined(BLOOM) && !(defined(RADIAL_BLUR) || defined(DEPTH_OF_FIELD) || defined(MOTION_BLUR_COMPOSIT))
uniform lowp sampler2D s_Texture0;		// Normal screen texture
uniform lowp sampler2D s_Texture1;		// Down sampled screen texture 0 (half dimensions)
uniform lowp sampler2D s_Texture2;		// Down sampled screen texture 1 (quarter dimensions)
uniform lowp sampler2D s_Texture3;		// Down sampled screen texture 2 (eighth dimensions)

varying lowp vec2 v_TexCoord;

uniform lowp float u_bloomHalfFactor;
uniform lowp float u_bloomQuarterFactor;
uniform lowp float u_bloomEighthFactor;

uniform lowp vec3 u_bloomTintColor;

void main()
{
	lowp vec3 c = texture2D( s_Texture0, v_TexCoord ).rgb;
//	lowp vec3 d1 = texture2D( s_Texture1, v_TexCoord ).rgb;
//	lowp vec3 d2 = texture2D( s_Texture2, v_TexCoord ).rgb;
	// 3x3 gaussian over the 1/8-res bloom layer (the stock code does one
	// bilinear tap, which leaves a blocky halo)
	highp vec2 btex = fwidth( v_TexCoord ) * 8.0;
	highp vec3 d3 = texture2D( s_Texture3, v_TexCoord ).rgb * 0.25;
	d3 += texture2D( s_Texture3, v_TexCoord + vec2( btex.x, 0.0 ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord - vec2( btex.x, 0.0 ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord + vec2( 0.0, btex.y ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord - vec2( 0.0, btex.y ) ).rgb * 0.125;
	d3 += texture2D( s_Texture3, v_TexCoord + btex ).rgb * 0.0625;
	d3 += texture2D( s_Texture3, v_TexCoord - btex ).rgb * 0.0625;
	d3 += texture2D( s_Texture3, v_TexCoord + vec2( btex.x, -btex.y ) ).rgb * 0.0625;
	d3 += texture2D( s_Texture3, v_TexCoord + vec2( -btex.x, btex.y ) ).rgb * 0.0625;

	d3 = d3 * d3 * d3;

	#ifdef BLOOM_DEBUG
		gl_FragColor = vec4( (
							 //  d1 * u_bloomHalfFactor
							 //+ d2 * u_bloomQuarterFactor
							 d3 * u_bloomEighthFactor
							 ) * u_bloomTintColor
							 , 1.0 );
	#else
		gl_FragColor = vec4(   c
							 + (
//							 d1 * u_bloomHalfFactor
//							 + d2 * u_bloomQuarterFactor
							 d3 * u_bloomEighthFactor
							 ) * u_bloomTintColor
							 , 1.0 );
	#endif
}
#endif


// ==============================================================
#ifdef COLOR_CURVES

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

uniform mediump vec3 u_Brightness;
uniform mediump vec3 u_Contrast;

void main()
{
	lowp vec3 color = FRAMEBUFFER_RGBA.rgb;
	
	color = (color - 0.5) * u_Contrast + 0.5;
	color *= u_Brightness;

	// half-LSB ordered dither: breaks up 8-bit banding in smooth gradients
	// without adding visible noise (R2 low-discrepancy sequence)
	highp float dth = fract( dot( gl_FragCoord.xy,
		vec2( 0.7548776662466927, 0.5698402909980532 ) ) );
	color += ( dth - 0.5 ) * ( 1.0 / 255.0 );

	gl_FragColor = vec4(color, 1.0);
}
#endif
