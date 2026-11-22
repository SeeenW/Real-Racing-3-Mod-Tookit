//
//  reflect_hemisphere.fsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

const lowp float c_one = 1.0;
const lowp float c_half = 0.5;

// Texture units
uniform lowp sampler2D s_Texture0;		// Building texture
uniform lowp sampler2D s_Texture1;		// Light map
uniform lowp sampler2D s_trackReflectionSphere;		// Hemi map
uniform lowp sampler2D s_Texture3;		// Alphamask map

// Vertex shader outputs
varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;
varying mediump vec2 v_HemiUV;
varying mediump float v_FresnelCoeff;

// Fog
#ifdef SUN_FOG
	varying lowp vec3 v_FogColour;
	varying lowp float v_FogFactor;
#else
	uniform lowp vec3 u_FogColour;
	varying lowp float v_FogFactor;
#endif

void main()
{
	#ifdef NOBIAS
		lowp vec4 diffuseTexture = texture2D( s_Texture0, v_TexCoord0 );
	#else
		lowp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );
	#endif
	lowp vec3 lightMap = texture2DWithBias( s_Texture1, v_TexCoord1 ).rgb;
	lowp vec3 hemiMap = texture2D( s_trackReflectionSphere, v_HemiUV ).rgb;
	
	// Diffuse colour
	lowp vec3 diffuse = getColourFromLightmap( lightMap );

	// Diffuse light
	diffuseTexture.rgb *= diffuse;

	// Hemi map
	#ifdef NIGHT
		diffuseTexture.rgb += texture2DWithBias( s_Texture3, v_TexCoord0 ).rgb;
	#else
		lowp float hemiMask = texture2DWithBias( s_Texture3, v_TexCoord0 ).g;
		diffuseTexture.rgb += hemiMap * (hemiMask * v_FresnelCoeff);
	#endif

	// Fog
	#ifdef SUN_FOG
		diffuseTexture.rgb = mix( diffuseTexture.rgb, v_FogColour, v_FogFactor );
	#else
		diffuseTexture.rgb = mix( diffuseTexture.rgb, u_FogColour, v_FogFactor );
	#endif

	gl_FragColor = diffuseTexture;
}

