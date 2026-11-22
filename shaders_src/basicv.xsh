//
//  basicv.xsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

//%feature FOG
//%feature SUN_FOG
//%feature ADD_FOG
//%feature PER_PIXEL_SPEC
//%feature SPEC_MAP
//%feature SHADOW_MAP
//%feature DETAIL_MAP
//%feature NOBIAS

//%feature NIGHT
//%feature HIGH_HL
//%feature LOW_HL
//%feature REFLECTOR
//%feature REFLECTOR_MARKER

//%feature CURRENT_COLOUR
//%feature VERTEX_COLOUR
//%feature ALPHA_MODULATE
//%feature ALPHA_TEST

//%feature CLOUDS
//%feature TRAMTRACKS

//%precompile -FOG -SPEC_MAP -PER_PIXEL_SPEC -DETAIL_MAP
//%precompile SUN_FOG
//%precompile SUN_FOG, NIGHT
//%precompile

const highp float c_zero = 0.0;
const highp float c_one = 1.0;

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute mediump vec2 a_TexCoord0;	//%attributeID MT_UV_0		Diffuse UV channel

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

varying mediump vec2 v_TexCoord0;

#ifdef PER_PIXEL_SPEC
	#ifndef REQUIRE_Normal
		#define REQUIRE_Normal					// NOTE: This isn't used at the moment, normals are assumed to be pointing straight up.
	#endif
	#ifndef REQUIRE_LightDirModelSpace
		#define REQUIRE_LightDirModelSpace
	#endif
	#ifndef REQUIRE_EyePosModelSpace
		#define REQUIRE_EyePosModelSpace
	#endif

	uniform mediump float mu_DiffuseFreq;

	varying highp vec3 v_HalfVectorModelSpace;
#endif

#ifdef SPEC_MAP
	#ifndef REQUIRE_Normal
		#define REQUIRE_Normal
	#endif
	#ifndef REQUIRE_LightDirModelSpace
		#define REQUIRE_LightDirModelSpace
	#endif
	#ifndef REQUIRE_EyePosModelSpace
		#define REQUIRE_EyePosModelSpace
	#endif
	uniform lowp vec3 u_LightSpecularColour;
	uniform highp float mu_MaterialSpecularPower;
	uniform highp float u_LightSpecExponentModifier;
	uniform lowp vec3 mu_MaterialSpecularColour;

	varying lowp vec3 v_SpecularColour;
#endif

#if defined(SHADOW_MAP)
	attribute mediump vec2 a_TexCoord1;		//%attributeID MT_UV_1		Shadow map UV channel
	varying mediump vec2 v_TexCoord1;
#endif

#ifdef VERTEX_COLOUR
	attribute lowp vec4 a_Colour;		//%attributeID MT_COLOUR	Vertex colour

	varying lowp vec4 v_VertexColour;
#endif

#ifdef DETAIL_MAP
	#ifndef REQUIRE_EyePosModelSpace
		#define REQUIRE_EyePosModelSpace
	#endif
	uniform mediump float mu_DiffuseFreq;
	uniform mediump float mu_DetailFreq;

	varying mediump vec2 v_DetailMapCoord;
#endif

#ifdef FOG
	#ifdef SUN_FOG
		#ifndef REQUIRE_EyePosModelSpace
			#define REQUIRE_EyePosModelSpace
		#endif
		#ifndef REQUIRE_LightDirModelSpace
			#define REQUIRE_LightDirModelSpace
		#endif

		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogColour;

		uniform highp vec3 u_FogSunParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogSunColour;
		uniform highp float u_FogSunPower;
	
		varying lowp vec3 v_FogColour;
		varying lowp float v_FogFactor;
	#else
		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		varying lowp float v_FogFactor;
	#endif
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
		uniform highp mat4 u_HeadLightMatrix;
		varying highp vec3 v_PosHeadLightSpace;
	#ifdef HIGH_HL
		#ifndef REQUIRE_Normal
			#define REQUIRE_Normal
		#endif
		varying mediump vec3 v_NormalHeadLightSpace;
	#endif
#endif

#ifdef REQUIRE_Normal
	attribute highp vec3 a_Normal;	//%attributeID MT_NORMAL
#endif
#ifdef REQUIRE_EyePosModelSpace
	uniform highp vec3 u_EyePosModelSpace;
#endif
#ifdef REQUIRE_LightDirModelSpace
	uniform highp vec3 u_LightDirModelSpace;
#endif

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	v_PosHeadLightSpace = (u_HeadLightMatrix * vec4(a_Position, 1.0)).xyz;
	#ifdef HIGH_HL
		v_NormalHeadLightSpace = (u_HeadLightMatrix * vec4(a_Normal, 0.0)).xyz;
	#endif
#endif

#ifdef DETAIL_MAP
	v_TexCoord0 = (a_TexCoord0 * mu_DiffuseFreq) * uvMult;
#else
	v_TexCoord0 = a_TexCoord0 * uvMult;
#endif

#if defined(SHADOW_MAP)
	v_TexCoord1 = a_TexCoord1 * uvMult;
#endif

#ifdef PER_PIXEL_SPEC
	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = u_EyePosModelSpace - a_Position;

	//Don't bother normalizing - do it in the fragment anyway
	v_HalfVectorModelSpace = (u_LightDirModelSpace * length( vertexToEyeModelSpace )) + vertexToEyeModelSpace;
#endif

#ifdef SPEC_MAP
	// Normal in model space
	highp vec3 normal = a_Normal;

	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = u_EyePosModelSpace - a_Position;

	// Half vector
	highp vec3 halfVector = normalize( (u_LightDirModelSpace * length( vertexToEyeModelSpace )) + vertexToEyeModelSpace );

	// N dot H
	highp float ndoth = max( c_zero, dot( normal, halfVector ) );

	// Specular colour
	v_SpecularColour = u_LightSpecularColour * mu_MaterialSpecularColour * pow( ndoth, mu_MaterialSpecularPower + u_LightSpecExponentModifier);
#endif

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

#ifdef DETAIL_MAP
	// Detail map
	calcDetailMapCoordVec( a_Position, u_EyePosModelSpace, mu_DetailFreq, v_DetailMapCoord);
#endif

#ifdef VERTEX_COLOUR
	// Colour
	v_VertexColour = a_Colour;
#endif

#ifdef FOG
	#ifdef SUN_FOG
		highp float sunFogFactor = clamp(dot(u_LightDirModelSpace, normalize(a_Position - u_EyePosModelSpace)), 0.0, 1.0);
		sunFogFactor = pow(sunFogFactor, u_FogSunPower);
		highp vec3 fogParams = mix(u_FogParams, u_FogSunParams, sunFogFactor);

		// Increase with distance up to max saturation
		v_FogFactor = clamp( (pos.w - fogParams.x) * fogParams.y, 0.0, fogParams.z );
		v_FogColour = mix(u_FogColour, u_FogSunColour, sunFogFactor);
	#else
		v_FogFactor = clamp( (pos.w - u_FogParams.x) * u_FogParams.y, 0.0, u_FogParams.z );
	#endif
#endif

	gl_Position = pos;
}

