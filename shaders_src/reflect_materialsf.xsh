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
uniform lowp sampler2D s_Texture2;		// Hemi map
uniform lowp sampler2D s_Texture3;		// Alphamask map

// Vertex shader outputs
varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;
varying mediump vec2 v_HemiUV;
varying mediump float v_FresnelCoeff;


#ifdef SPEC_MAP
	uniform lowp sampler2D s_Texture4;		// Spec map texture
	varying lowp vec3 v_SpecularColour;
#endif


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
	lowp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );
	lowp vec3 lightMap = texture2DWithBias( s_Texture1, v_TexCoord1 ).rgb;
	lowp vec3 hemiMap = texture2D( s_Texture2, v_HemiUV ).rgb;
	lowp float hemiMask = texture2DWithBias( s_Texture3, v_TexCoord0 ).g;
	
		#ifdef WHITE
	diffuseTexture.rgb = float3(0.5,0.5,0.4);
	#endif
	
	//hemiMap= hemiMap + float3(0.5,0.8,0.4);
	
	// Diffuse colour
	lowp vec3 diffuse = getColourFromLightmap( lightMap );

	// Diffuse light
	diffuseTexture.rgb *= diffuse;

	// Hemi map
	diffuseTexture.rgb += hemiMap * (hemiMask * v_FresnelCoeff);
	

	
	#ifdef SPEC_MAP
	lowp vec3 specMap = texture2DWithBias( s_Texture4, v_TexCoord0 ).rgb;

	// Specular colour
	lowp vec3 specular = v_SpecularColour * specMap;
	// Specular light
	diffuseTexture.rgb += specular*lightMap;
#endif
	


	// Fog
	#ifdef SUN_FOG
		diffuseTexture.rgb = mix( diffuseTexture.rgb, v_FogColour, v_FogFactor );
	#else
		diffuseTexture.rgb = mix( diffuseTexture.rgb, u_FogColour, v_FogFactor );
	#endif

	gl_FragColor = diffuseTexture;
}

