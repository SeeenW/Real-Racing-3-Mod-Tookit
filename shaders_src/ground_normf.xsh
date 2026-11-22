//
//  ground_norm.fsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

precision highp float;

const highp float c_zero = 0.0;
const lowp float c_one = 1.0;
const lowp float c_two = 2.0;
const lowp float c_diffuseFactor = 1.21;

// Texture units
uniform lowp sampler2D s_Texture0;		// Diffuse map
uniform lowp sampler2D s_Texture1;		// Light map texture

#ifdef DETAIL
	uniform lowp sampler2D s_Texture2;		// detail normal map texture and detail map texture in the alpha
	varying mediump vec2 v_DetailMapCoord;
#endif

#ifdef SPEC_MASK_TEXTURE
	uniform lowp sampler2D s_Texture3;		// Spec mask texture
#endif

#ifdef SPEC
	#ifdef PER_PIXEL_SPEC
		#ifndef REQUIRE_PosModelSpace
			#define REQUIRE_PosModelSpace
		#endif

		// Light information
		uniform lowp vec3 u_LightSpecularColour;
		uniform highp vec3 u_EyePosModelSpace;
		uniform highp vec3 u_LightDirModelSpace;
		uniform highp float u_LightSpecExponentModifier;

		// Material spreadsheet uniforms
		uniform mediump float mu_MaterialSpecularPower;
		uniform lowp vec3 mu_MaterialSpecularColour;
	#else
		// Light information
		varying lowp vec3 v_SpecularColour;
	#endif

	uniform mediump float u_LightSpecularShadowCutoff;
#endif

#ifdef FOG
	#ifdef SUN_FOG
		varying lowp vec3 v_FogColour;
		varying lowp float v_FogFactor;
	#else
		uniform lowp vec3 u_FogColour;
		varying lowp float v_FogFactor;
	#endif
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	uniform mediump vec4 u_HeadLightFalloff;
	uniform mediump vec2 u_HeadLightAtten;
	uniform mediump vec3 u_HeadLightColour;
	varying highp vec3 v_PosHeadLightSpace;
	#ifdef HIGH_HL
		varying mediump vec3 v_NormalHeadLightSpace;
	#endif
#endif

#ifdef REQUIRE_PosModelSpace
	varying highp vec3 v_PosModelSpace;
#endif

// Game uniforms

// Vertex shader outputs
varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;

void main()
{
	lowp vec4 diffuseMap = texture2DWithBias( s_Texture0, v_TexCoord0 );

#if defined(DETAIL) || defined(SPEC)
	lowp vec3 lightMap = texture2DWithBias( s_Texture1, v_TexCoord1 ).rgb;
#endif

#ifdef DETAIL
	lowp vec4 normalMap = texture2D( s_Texture2, v_DetailMapCoord );
#endif

#if defined(ROAD_NEW)
	lowp float specmask = diffuseMap.g;
	diffuseMap.g = diffuseMap.r;
#elif defined(SPEC_MASK_TEXTURE)
	lowp float specmask = texture2D( s_Texture3, v_TexCoord0 ).g;
#endif

#ifdef SPEC
	#ifdef PER_PIXEL_SPEC
		#ifdef DETAIL
			// Fragment normal
			mediump vec3 normal = normalize( (normalMap.rgb * c_two) - c_one );
		#else
			mediump vec3 normal = vec3( 0.0, 1.0, 0.0 );
		#endif

		mediump vec3 vertToEyeModelSpace = normalize( u_EyePosModelSpace - v_PosModelSpace );
		mediump vec3 halfVec = normalize( u_LightDirModelSpace + vertToEyeModelSpace );
		// N dot H
		mediump float ndoth = max( c_zero, dot( normal, halfVec ) );
	#endif
#endif

#ifdef SPEC
	#ifdef PER_PIXEL_SPEC
		// Specular colour
		highp vec3 specular = u_LightSpecularColour * mu_MaterialSpecularColour * pow( ndoth, mu_MaterialSpecularPower + u_LightSpecExponentModifier );
	#else
		lowp vec3 specular = v_SpecularColour.rgb;
	#endif
	
	// Modulate the spec by the spec texture
	#if defined(ROAD_NEW) || defined(SPEC_MASK_TEXTURE)
		specular *= specmask;
	#else
		specular *= diffuseMap.a;
	#endif
	
	// Darken the spec in shadows
	applyLightmapIntensityToColour( specular, lightMap, u_LightSpecularShadowCutoff );
#endif


#ifdef DETAIL
	// Diffuse colour
	mediump vec3 diffuse = diffuseMap.rgb;

	mediump vec3 lm = getColourFromLightmap(lightMap);
	// Apply lightmap
	diffuse *= lm;

	// Detail texture
//	diffuse *= normalMap.a * 2.0;
	diffuse += (normalMap.a - 0.425) * 0.5;

#ifdef SPEC
	//specular += (normalMap.a - 0.5) * 1.0;
	specular += ((normalMap.a - 0.425) * 0.65) * lm * lm;

#endif
	lowp vec4 fragColour = vec4(diffuse, c_one);
#else
	lowp vec4 fragColour = diffuseMap;
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	mediump float headLightCoeff = 0.0;
	#ifdef HIGH_HL
		calculateHeadLightCoeff(v_NormalHeadLightSpace, v_PosHeadLightSpace, u_HeadLightFalloff, u_HeadLightAtten, headLightCoeff);
	#else
		calculateCheapHeadLightCoeff(v_PosHeadLightSpace, u_HeadLightFalloff, u_HeadLightAtten, headLightCoeff);
	#endif
	#ifdef DETAIL
		headLightCoeff *= normalMap.a;
	#endif
	fragColour.rgb += (diffuseMap.rgb * u_HeadLightColour) * (c_diffuseFactor * headLightCoeff);
#endif
	
#ifdef SPEC
	// Specular light
	fragColour.rgb += specular;
#endif

#ifdef FOG
	#ifdef SUN_FOG
		fragColour.rgb = mix( fragColour.rgb, v_FogColour, v_FogFactor );
	#else
		fragColour.rgb = mix( fragColour.rgb, u_FogColour, v_FogFactor );
	#endif
#endif

	gl_FragColor = fragColour;

	//gl_FragColor = vec4( diffuseMap.rgb /1.65, c_one );
	//gl_FragColor = vec4( vec3( diffuseMap.a ), c_one );
	//gl_FragColor = vec4 (specMap, c_one);
	//gl_FragColor = vec4( normalMap.rgb, c_one );
	//gl_FragColor = vec4( vec3( normalMap.a ), c_one );
	//gl_FragColor = vec4( specular, c_one );
	//gl_FragColor = vec4( lightMap, c_one );
	
/*#if QUALITY_LEVEL == 0
	gl_FragColor = vec4( 0.2, 0.2, 0.2, 1.0 );
#elif QUALITY_LEVEL == 1
	gl_FragColor = vec4( 0.4, 0.4, 0.4, 1.0 );
#elif QUALITY_LEVEL == 2
	gl_FragColor = vec4( 0.6, 0.6, 0.6, 1.0 );
#elif QUALITY_LEVEL == 3
	gl_FragColor = vec4( 0.8, 0.8, 0.8, 1.0 );
#else
	gl_FragColor = vec4( 0.0, 0.0, 1.0, 1.0 );
#endif */
}

