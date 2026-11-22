//
//  car_interior.fsh
//
//  Created by bend on 10/07/12.
//  Copyright Electronic Arts 2012. All rights reserved.

//%include utility.xsh

precision mediump float;

// Texture samplers
uniform lowp sampler2D s_Texture0;				// Base texture
uniform lowp samplerCube s_cubeMap;				// Blurred cube map

uniform lowp sampler2D s_Texture3;				// Fresnel texture
uniform lowp sampler2D s_Texture4;				// Spec texture

uniform lowp sampler2D s_InteriorShadow0;				// Animated shadow 1
uniform lowp vec3 u_InteriorShadowChannel0;				// Animated shadow channel mask 1
uniform lowp sampler2D s_InteriorShadow1;				// Animated shadow 2
uniform lowp vec3 u_InteriorShadowChannel1;				// Animated shadow channel mask 2

uniform lowp float u_ShadowInterpolationFactor;	// Shadow texture interpolation factor

#ifdef USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
	uniform lowp float u_LightDiffuseScaleFactor;	// Scale factor for diffuse light, decreases when in shadows.
#endif

uniform lowp vec3 u_LightAmbientInteriorColour;	// Ambient light for the interior
uniform lowp vec3 u_LightSpecularColour;		// Specular light colour

varying mediump vec2 v_TexCoord0;					// Base UVs
varying mediump vec2 v_TexCoord1;					// Shadow UVs
varying mediump vec2 v_EdotN;						// Fresnel texture coord
varying lowp vec3 v_CubeRay;						// Cubemap ray
varying lowp float v_CubeReflectionModulate;

varying lowp vec3 v_DiffuseColour;
varying highp vec3 v_VertexNormalModelSpace;
varying highp vec3 v_HalfVectorModelSpace;


#ifdef USE_SHADOW_MAP
	uniform lowp sampler2D s_CarShadowMapTexture;
	varying lowp vec2 v_ShadowUV;
	uniform lowp vec3 u_ShadowChannel;
#endif

void main()
{
	lowp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );
	lowp vec3 blurredCubeMap = textureCube( s_cubeMap, v_CubeRay ).rgb;
	
	lowp vec3 fresnelTerm = texture2D( s_Texture3, v_EdotN ).rgb;

	// These are greyscale, packed on a per channel basis.
	lowp float shadow1 = dot(texture2DWithBias(s_InteriorShadow0, v_TexCoord1).rgb, u_InteriorShadowChannel0);
	lowp float shadow2 = dot(texture2DWithBias(s_InteriorShadow1, v_TexCoord1).rgb, u_InteriorShadowChannel1);

	// The u_ShadowInterpolationFactor is used to blend between the two shadow textures, it changes as the car rotates.
	lowp float shadowModulate = mix(shadow1, shadow2, u_ShadowInterpolationFactor);

#ifdef USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
	lowp float shadowMin = min( 0.6, u_LightDiffuseScaleFactor );
	shadowModulate = mix( shadowMin, u_LightDiffuseScaleFactor, shadowModulate );
#endif

#ifdef USE_SHADOW_MAP
	lowp float shadowMap = dot( texture2DWithBias( s_CarShadowMapTexture, v_ShadowUV ).rgb, u_ShadowChannel );
	shadowMap = min( 1.0, shadowMap + 0.2 );
	lowp float shadowMin = min( 0.6, shadowMap );
	shadowModulate = mix( shadowMin, shadowMap, shadowModulate );
#endif

	// Texture
	lowp vec4 fragColour = diffuseTexture;

	// Ambient and diffuse light
	fragColour.rgb *= v_DiffuseColour + u_LightAmbientInteriorColour;

	// Soft cubemap reflection
	fragColour.rgb += blurredCubeMap * fresnelTerm * v_CubeReflectionModulate;

	// Per pixel spec, looked up from a texture.
	highp vec3 normal = normalize( v_VertexNormalModelSpace );
	highp vec3 halfVector = normalize( v_HalfVectorModelSpace );
	highp float ndoth = max( 0.0, dot( normal, halfVector ) );
	ndoth = clamp( ndoth * ndoth, 0.1, 0.999 );
	lowp vec3 specular = u_LightSpecularColour * texture2D( s_Texture4, vec2( ndoth, 0.0 ) ).rgb;

	// Add the spec in...
	// - Darken the spec even more in shadows.
	// - Modulate by the green channel as well. This softens the spec even more, and provides some variation.
	fragColour.rgb += specular * shadowModulate * diffuseTexture.g;

#ifndef USE_SH_LIGHTING
	// Darken in the shadows
	fragColour.rgb *= shadowModulate;
#endif

#ifdef DIFFUSE_LIGHTING
	gl_FragColor = vec4(v_DiffuseColour + u_LightAmbientInteriorColour, 1.0);
#else
	gl_FragColor = fragColour;
#endif
}

