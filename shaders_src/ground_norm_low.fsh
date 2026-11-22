//
//  ground_norm_low.vsh
//
//  Created by Patrick on 20/09/12.
//  Copyright Electronic Arts 2012. All rights reserved.
//

//%include utility.xsh

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;
const lowp float c_diffuseFactor = 1.44;

// Texture units
uniform lowp sampler2D s_Texture0;		// diffuse
uniform lowp sampler2D s_Texture1;		// Light map texture
uniform lowp sampler2D s_Texture3;		// Tiled high res diffuse texture (tiled based on the detail frequency)

// Game uniforms
uniform lowp vec3 u_FogColour;

// Vertex shader outputs
varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;
varying mediump vec2 v_DetailMapCoord;
varying lowp vec4 v_Spec_Fog;

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	uniform mediump vec4 u_HeadLightFalloff;
	uniform mediump vec2 u_HeadLightAtten;
	uniform mediump vec3 u_HeadLightColour;
	varying highp vec3 v_PosHeadLightSpace;
#endif

void main()
{
	lowp vec4 diffuseMap = texture2DWithBias( s_Texture0, v_TexCoord0 );
	lowp vec3 detailMap = texture2D( s_Texture3, v_DetailMapCoord ).rgb;
	lowp vec3 lightMap = texture2DWithBias( s_Texture1, v_TexCoord1 ).rgb;
	
	// Extract specmask from green channel
	#ifdef ROAD_NEW
		lowp float specmask = diffuseMap.g;
		diffuseMap.g = diffuseMap.r;
	#endif

	// Detail map
	diffuseMap.rgb *= detailMap * c_diffuseFactor;

	// Light map
	lowp vec4 fragColour = diffuseMap;
	fragColour.rgb *= lightMap;
	
#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	mediump float headLightCoeff = 0.0;
	calculateCheapHeadLightCoeff(v_PosHeadLightSpace, u_HeadLightFalloff, u_HeadLightAtten, headLightCoeff);
	fragColour.rgb += diffuseMap.rgb * u_HeadLightColour * headLightCoeff;
#endif

#ifdef PER_VERTEX_SPEC
	// Modulate the spec by the spec texture and darken the spec in shadows
	lowp vec3 specular = v_Spec_Fog.rgb * (diffuseMap.a * lightMap.g * lightMap.g);

	// Specular light
	fragColour.rgb += specular;
#endif

	// Fog
	fragColour.rgb = mix( fragColour.rgb, u_FogColour, v_Spec_Fog.a );

	gl_FragColor = fragColour;

	//gl_FragColor = vec4( diffuseMap.rgb, c_one );
	//gl_FragColor = vec4( vec3( diffuseMap.a ), c_one );
	//gl_FragColor = vec4( vec3( detailMap.a ), c_one );
	//gl_FragColor = vec4( detailMap.rgb, c_one );
	//gl_FragColor = vec4( specular, c_one );
	//gl_FragColor = vec4( lightMap, c_one );
}
