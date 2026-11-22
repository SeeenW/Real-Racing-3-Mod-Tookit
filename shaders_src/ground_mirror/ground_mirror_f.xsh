//
//  ground_mirror.fsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//


precision mediump float;

const mediump float c_zero = 0.0;
const lowp float c_one = 1.0;
const lowp float c_two = 2.0;
const lowp float c_diffuseFactor = 0.5;

// Texture units
uniform lowp sampler2D s_Texture0;		// diffuse, and spec/refl texture in alpha
uniform lowp sampler2D s_Texture1;		// Light map texture

#ifdef NORMAL_MAP
uniform lowp sampler2D s_Texture2;
#endif

// Light information
uniform lowp vec3 u_LightSpecularColour;
uniform mediump float u_LightSpecularShadowCutoff;
uniform highp float u_LightSpecExponentModifier;

// Game uniforms
#ifdef FOG
	#ifdef SUN_FOG
		varying lowp vec3 v_FogColour;
		varying lowp float v_FogFactor;
	#else
		uniform lowp vec3 u_FogColour;
		varying lowp float v_FogFactor;
	#endif
#endif

// Material spreadsheet uniforms
uniform mediump float mu_MaterialSpecularPower;
uniform lowp vec3 mu_MaterialSpecularColour;

// Vertex shader outputs
varying highp vec2 v_TexCoord0;
varying highp vec2 v_TexCoord1;
varying highp vec3 v_HalfVector;
varying mediump float v_FogFactor;

void main()
{
	lowp vec4 difusespec = texture2DWithBias( s_Texture0, v_TexCoord0 );
	lowp vec3 lightMap = texture2DWithBias( s_Texture1, v_TexCoord1 ).rgb;

	lowp float specMap = difusespec.a;

#ifdef NORMAL_MAP	
	// Fragment normal
	lowp vec3 normalMap = texture2DWithBias( s_Texture2, v_TexCoord0 ).rgb;
	mediump vec3 normal = normalize( (normalMap * c_two) - c_one );
#else
	lowp vec3 normal = vec3(0,1,0);
#endif

	// Half vector
	mediump vec3 halfVector = normalize(v_HalfVector);

	// N dot H
	mediump float ndoth = max( c_zero, dot( normal, halfVector ) );

	// Diffuse colour
	lowp vec3 diffuse = getColourFromLightmap( lightMap );

	// Modulate the diffuse by the detail texture
	// Halfing the texture to compensate (c_diffuseFactor)
	// This is because the texture is added to itself to help with the alpha colour distortion
	diffuse *= difusespec.rgb * c_diffuseFactor;

#if 0
	// Specular colour
	lowp vec3 specular = (u_LightSpecularColour * mu_MaterialSpecularColour) * pow( ndoth, mu_MaterialSpecularPower + u_LightSpecExponentModifier);

	// Modulate the spec by the spec texture
	specular *= difusespec.a;
#endif

	//Same as above - just simpler
	lowp vec3 specular = (u_LightSpecularColour * mu_MaterialSpecularColour) * ( pow( ndoth, mu_MaterialSpecularPower + u_LightSpecExponentModifier) * difusespec.a);

	// Darken the spec in shadows
	applyLightmapIntensityToColour( specular, lightMap, u_LightSpecularShadowCutoff );

	// Texture
	lowp vec4 fragColour = vec4(difusespec.a);

	// Diffuse light
	fragColour.rgb *= diffuse;

	// Specular light
	fragColour.rgb += specular;
	
#ifdef FOG
	#ifdef SUN_FOG
		fragColour.rgb = mix( fragColour.rgb, v_FogColour, v_FogFactor );
	#else
		fragColour.rgb = mix( fragColour.rgb, u_FogColour, v_FogFactor );
	#endif
#endif
	
	gl_FragColor = fragColour;

	//gl_FragColor = vec4( difusespec.rgb, c_one );
	//gl_FragColor = vec4( vec3( difusespec.a ), c_one );
	//gl_FragColor = vec4( normalMap, c_one );
	//gl_FragColor = vec4( specular, c_one );
}

