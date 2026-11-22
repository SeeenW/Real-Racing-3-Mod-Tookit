//
//  basicf.xsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

precision highp float;

uniform lowp sampler2D s_Texture0;		// Diffuse texture

varying mediump vec2 v_TexCoord0;

const highp float c_zero = 0.0;
const lowp float c_one = 1.0;
const lowp float c_two = 2.0;

#if defined(CLOUDS) || defined(SHADOW_MAP)
	uniform lowp sampler2D s_Texture1;		// Cloud texture
#endif

#if defined(SHADOW_MAP)
	varying mediump vec2 v_TexCoord1;
#endif

#ifdef SHADOW_MAP
	#if defined(SPEC_MAP) || defined(PER_PIXEL_SPEC)
		uniform mediump float u_LightSpecularShadowCutoff;
	#endif
#endif

#ifdef PER_PIXEL_SPEC
	uniform lowp sampler2D s_Texture2;		// Normal map texture
	uniform lowp vec3 u_LightSpecularColour;
	uniform highp float mu_MaterialSpecularPower;
	uniform highp float u_LightSpecExponentModifier;
	uniform lowp vec3 mu_MaterialSpecularColour;
	varying highp vec3 v_HalfVectorModelSpace;
#endif

#ifdef SPEC_MAP
	uniform lowp sampler2D s_Texture2;		// Spec map texture

	varying lowp vec3 v_SpecularColour;
#endif

#ifdef DETAIL_MAP
	uniform lowp sampler2D s_Texture2;		// Detail map texture (tiled based on the detail frequency)
	uniform lowp float mu_DetailIntensity;

	varying mediump vec2 v_DetailMapCoord;
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

#ifdef CURRENT_COLOUR
	uniform lowp vec4 u_CurrentColour;
#endif

#ifdef VERTEX_COLOUR
	varying lowp vec4 v_VertexColour;
#endif

#ifdef ALPHA_MODULATE
	uniform lowp float u_AlphaModulate;
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

void main()
{
#ifdef NOBIAS
		lowp vec4 diffuseTexture = texture2D( s_Texture0, v_TexCoord0 );
#else
		highp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );
#endif

#ifdef TRAMTRACKS
	lowp float specmask = diffuseTexture.g;
	diffuseTexture.g = diffuseTexture.r;
#endif

	lowp vec4 fragColour = diffuseTexture;

#ifdef ALPHA_TEST // for testing
	if (fragColour.a < 0.35)
	{
		discard;
	}
#endif

#ifdef CLOUDS
	lowp vec4 cloudTexture = texture2DWithBias( s_Texture1, v_TexCoord0 );
	fragColour.rgb *= (c_one - cloudTexture.a);
	fragColour.rgb += (cloudTexture.rgb*cloudTexture.a);
#endif 

#ifdef PER_PIXEL_SPEC
	lowp vec3 normalMap = texture2DWithBias( s_Texture2, v_TexCoord0 ).rgb;

	// Fragment normal
	highp vec3 normal = normalize( (normalMap * c_two) - c_one );

	// Half vector
	highp vec3 halfVector = normalize( v_HalfVectorModelSpace );

	// N dot H
	highp float ndoth = max( c_zero, dot( normal, halfVector ) );

	// Specular colour
	highp vec3 specular = u_LightSpecularColour * mu_MaterialSpecularColour * pow( ndoth, mu_MaterialSpecularPower + u_LightSpecExponentModifier);

	#ifdef TRAMTRACKS
		// Modulate the spec by the green channel of the diffuse texture
		specular *= specmask;
	#else
		// Modulate the spec by the alpha channel in the diffuse texture
		specular *= (fragColour.a);
	#endif
	fragColour.a = c_one;
#endif

#ifdef SPEC_MAP
	lowp vec3 specMap = texture2DWithBias( s_Texture2, v_TexCoord0 ).rgb;

	// Specular colour
	lowp vec3 specular = v_SpecularColour * specMap;
#endif

#if defined(SHADOW_MAP)
	lowp vec3 lightMap = texture2DWithBias( s_Texture1, v_TexCoord1 ).rgb;
#endif

#ifdef SHADOW_MAP
	fragColour.rgb *= getColourFromLightmap( lightMap );

	#if defined(SPEC_MAP) || defined(PER_PIXEL_SPEC)
		// Darken the spec in shadows
		applyLightmapIntensityToColour( specular, lightMap, u_LightSpecularShadowCutoff );
	#endif
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	mediump float headLightCoeff = 0.0;
	#ifdef HIGH_HL
		calculateHeadLightCoeff(v_NormalHeadLightSpace, v_PosHeadLightSpace, u_HeadLightFalloff, u_HeadLightAtten, headLightCoeff);
	#else
		calculateCheapHeadLightCoeff(v_PosHeadLightSpace, u_HeadLightFalloff, u_HeadLightAtten, headLightCoeff);
	#endif
	#ifdef REFLECTOR
		headLightCoeff = min(headLightCoeff * 5.0, 5.5);
	#endif
	#ifdef REFLECTOR_MARKER
		headLightCoeff = min(headLightCoeff * 7.0, 5.5);
	#endif
	fragColour.rgb += diffuseTexture.rgb * u_HeadLightColour * headLightCoeff;
#endif

#ifdef DETAIL_MAP
	//fragColour.rgb *= texture2D( s_Texture2, v_DetailMapCoord ).rgb * mu_DetailIntensity;
	mediump vec3 detailMap = texture2D(s_Texture2, v_DetailMapCoord).rgb;

	#if defined(SHADOW_MAP)
		fragColour.rgb += (detailMap - 0.5) * lightMap;
	#else
		fragColour.rgb += (detailMap - 0.5);
	#endif

#endif

#ifndef PF_DONT_USE_CURRENT_COLOR //~???
#ifdef CURRENT_COLOUR
	fragColour *= u_CurrentColour;
#endif
#endif

#ifdef VERTEX_COLOUR
	// Vertex colour
	fragColour *= v_VertexColour;
#endif
	
#if defined(SPEC_MAP) || defined(PER_PIXEL_SPEC)
	// Specular light
	fragColour.rgb += specular;
#endif

#ifdef FOG
	#ifdef ADD_FOG
		fragColour.rgb *= (1.0 - v_FogFactor); // can't mix fog color with ADD blended stuff (makes transparent regions look opaque)
	#else
		#ifdef SUN_FOG
			fragColour.rgb = mix( fragColour.rgb, v_FogColour, v_FogFactor );
		#else
			fragColour.rgb = mix( fragColour.rgb, u_FogColour, v_FogFactor );
		#endif
	#endif
#endif

#ifdef ALPHA_MODULATE
	fragColour.a *= u_AlphaModulate;
#endif

	gl_FragColor = fragColour;

/*#if QUALITY_LEVEL == 0
	gl_FragColor = vec4( 0.0, 1.0, 1.0, 1.0 );
#elif QUALITY_LEVEL == 1
	gl_FragColor = vec4( 0.3, 0.70, 1.0, 1.0 );:
	
#elif QUALITY_LEVEL == 2
	gl_FragColor = vec4( 0.5, 0.5, 1.0, 1.0 );
#elif QUALITY_LEVEL == 3
	gl_FragColor = vec4( 0.75, 0.25, 1.0, 1.0 );
#else
	gl_FragColor = vec4( 1.0, 0.0, 1.0, 1.0 );
#endif*/
}

