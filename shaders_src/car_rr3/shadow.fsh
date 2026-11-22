//
//  shadow.fsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//
//%include utility.xsh

precision mediump float;

// Texture units
uniform lowp sampler2D s_ShadowTexture0;			// Shadow texture 1
uniform lowp vec3 u_ShadowChannel0;					// Shadow channel mask 1
uniform lowp sampler2D s_ShadowTexture1;			// Shadow texture 2
uniform lowp vec3 u_ShadowChannel1;					// Shadow channel mask 2
uniform lowp float u_ShadowInterpolationFactor;		// Shadow blend factor

// Game uniforms
uniform lowp vec4 u_CurrentColour;

// Vertex shader outputs
varying mediump vec2 v_TexCoord0;
varying lowp float v_FogFactor;
varying lowp vec3 v_VertColor;

#ifdef USE_SHADOW_MAP
	uniform lowp sampler2D s_CarShadowMapTexture;
	varying lowp vec2 v_ShadowUV;
	uniform lowp vec3 u_ShadowChannel;
#endif

void main()
{
	lowp float shadowColor1raw = dot(texture2DWithBias(s_ShadowTexture0, v_TexCoord0).rgb, u_ShadowChannel0);
	lowp float shadowColor2raw = dot(texture2DWithBias(s_ShadowTexture1, v_TexCoord0).rgb, u_ShadowChannel1);
	lowp vec3 shadowColor1 = vec3(shadowColor1raw, shadowColor1raw, shadowColor1raw);
	lowp vec3 shadowColor2 = vec3(shadowColor2raw, shadowColor2raw, shadowColor2raw);
	lowp vec3 diffuseTexture = vec3(1.0) - mix( shadowColor1, shadowColor2, u_ShadowInterpolationFactor );

#ifdef USE_SHADOW_MAP
	lowp float shadowMap = dot( texture2DWithBias( s_CarShadowMapTexture, v_ShadowUV ).rgb, u_ShadowChannel );
	diffuseTexture *= shadowMap * shadowMap;
#endif
	
	diffuseTexture *= ( v_VertColor + u_CurrentColour.rgb )* v_FogFactor;
	gl_FragColor = vec4( diffuseTexture, 1.0 );
	//gl_FragColor = vec4(1.0,0,0,1.0);
	//gl_FragColor = v_VertColor;
}
