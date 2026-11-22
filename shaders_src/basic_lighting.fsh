//
//  basic_lighting.fsh
//
//  Copyright Electronic Arts 2012. All rights reserved.
//

//%include utility.xsh

#ifndef ENABLE_SHADER_FEATURES

// Enable high-quality fog
#ifndef SUN_FOG
#define SUN_FOG
#endif

#endif//ENABLE_SHADER_FEATURES

// Texture units
uniform lowp sampler2D s_Texture0;		// Diffuse texture

precision mediump float;

// Vertex shader outputs
varying mediump vec2 v_TexCoord0;
varying highp vec3 v_VertexNormalModelSpace;
varying lowp vec3 v_DiffuseColour;

#ifdef FOG
	#ifdef SUN_FOG
		varying lowp vec3 v_FogColour;
		varying lowp float v_FogFactor;
	#else
		uniform lowp vec3 u_FogColour;
		varying lowp float v_FogFactor;
	#endif
#endif

#ifdef WIREFENCE
	const lowp float c_fenceScale = 1.85;
#endif

#ifdef TREES
	uniform lowp vec3 u_TreeAmbientColour;
	uniform lowp vec2 mu_TreeDiffAmbScale;
#else
	uniform lowp vec3 u_LightAmbientColour;
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	uniform mediump vec4 u_HeadLightFalloff;
	uniform mediump vec2 u_HeadLightAtten;
	uniform mediump vec3 u_HeadLightColour;
	varying highp vec3 v_PosHeadLightSpace;
#endif

#ifdef ALPHA_MODULATE
	uniform lowp float u_AlphaModulate;
#endif

void main()
{
	lowp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );
	
	// Diffuse + Ambient lighting
#ifdef TREES
	diffuseTexture.rgb *= (v_DiffuseColour * mu_TreeDiffAmbScale.x + u_TreeAmbientColour * mu_TreeDiffAmbScale.y);
#else
	diffuseTexture.rgb *= (v_DiffuseColour + u_LightAmbientColour);
#endif

#ifdef WIREFENCE
	diffuseTexture.rgb *= (v_DiffuseColour + u_LightAmbientColour) * c_fenceScale;
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	mediump float headLightCoeff = 0.0;
	calculateCheapHeadLightCoeff( v_PosHeadLightSpace, u_HeadLightFalloff, u_HeadLightAtten, headLightCoeff );
	diffuseTexture.rgb += diffuseTexture.rgb * u_HeadLightColour * headLightCoeff;
#endif

#ifdef FOG
	#ifdef ADD_FOG
		diffuseTexture.rgb *= (1.0 - v_FogFactor); // can't mix fog color with ADD blended stuff (makes transparent regions look opaque)
	#else
		#ifdef SUN_FOG
			diffuseTexture.rgb = mix( diffuseTexture.rgb, v_FogColour, v_FogFactor );
		#else
			diffuseTexture.rgb = mix( diffuseTexture.rgb, u_FogColour, v_FogFactor );
		#endif
	#endif
#endif

#ifdef ALPHA_MODULATE
	diffuseTexture.a *= u_AlphaModulate;
#endif

	gl_FragColor = diffuseTexture;
}
