//
//  ground_norm.vsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

// Default quality
//%0define QUALITY_LEVEL 0
//%0define DETAIL

// Used when drawing to cubemap
//%1define QUALITY_LEVEL 1
//%1define DETAIL
//%1undef SPEC
//%1undef FOG

//%2define QUALITY_LEVEL 0
//%2define DETAIL
//%2define NIGHT

//////////////////////////////////// NEW FEATURES SYSTEM

//%feature ROAD_NEW
//%feature FOG
//%feature SUN_FOG
//%feature SPEC
//%feature PER_PIXEL_SPEC
//%feature DETAIL
//%feature NIGHT
//%feature HIGH_HL
//%feature LOW_HL
//%feature SPEC_MASK_TEXTURE

//%precompile DETAIL, -FOG, -SPEC, -PER_PIXEL_SPEC
//%precompile DETAIL, SUN_FOG
//%precompile DETAIL, SUN_FOG, NIGHT

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

attribute highp vec3 a_Position;		//%attributeID MT_POS
attribute mediump vec2 a_TexCoord0;		//%attributeID MT_UV_0		Diffuse UV channel
attribute mediump vec2 a_TexCoord1;		//%attributeID MT_UV_1		Shadow map UV channel

uniform highp vec3 u_EyePosModelSpace;

#ifdef SPEC
	// Light info
	uniform highp vec3 u_LightDirModelSpace;
	attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL			NOTE: This isn't used at the moment, normals are assumed to be pointing straight up.
	
	#ifdef PER_PIXEL_SPEC
		#ifndef REQUIRE_PosModelSpace
			#define REQUIRE_PosModelSpace
		#endif
	#else
		// Light information
		uniform lowp vec3 u_LightSpecularColour;
		varying lowp vec3 v_SpecularColour;

		// Material spreadsheet uniforms
		uniform mediump float mu_MaterialSpecularPower;
		uniform lowp vec3 mu_MaterialSpecularColour;
	#endif
#endif

#ifdef FOG
	#ifdef SUN_FOG
		#if !defined(SPEC)
			uniform highp vec3 u_LightDirModelSpace;
		#endif
		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogColour;
		uniform highp vec3 u_FogSunParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogSunColour;
		uniform highp float u_FogSunPower;

		varying lowp float v_FogFactor;
		varying lowp vec3 v_FogColour;
	#else
		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		varying lowp float v_FogFactor;
	#endif
#endif

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

// Material uniforms
uniform mediump float mu_DiffuseFreq;

varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;

#ifdef DETAIL
	uniform mediump float mu_DetailFreq;
	varying mediump vec2 v_DetailMapCoord;
	uniform mediump float u_detailTextureOffset;
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	uniform highp mat4 u_HeadLightMatrix;
	varying highp vec3 v_PosHeadLightSpace;
	#ifdef HIGH_HL
		varying mediump vec3 v_NormalHeadLightSpace;
	#endif
#endif

#ifdef REQUIRE_PosModelSpace
	varying highp vec3 v_PosModelSpace;
#endif

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	// Texture coords
	v_TexCoord0 = (a_TexCoord0 * mu_DiffuseFreq) * uvMult;
	v_TexCoord1 = a_TexCoord1 * uvMult;

#if defined(SPEC) || defined(FOG)
	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = normalize(u_EyePosModelSpace - a_Position);
#endif

#ifdef REQUIRE_PosModelSpace
	v_PosModelSpace = a_Position;
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	v_PosHeadLightSpace = (u_HeadLightMatrix * vec4(a_Position, 1.0)).xyz;
	#ifdef HIGH_HL
		v_NormalHeadLightSpace = u_HeadLightMatrix[1].xyz; //assuming normal is (0,1,0)
	#endif
#endif

#ifdef SPEC
	#ifndef PER_PIXEL_SPEC
		mediump vec3 halfVector = normalize( u_LightDirModelSpace + vertexToEyeModelSpace );

		// N dot H (NOTE: per-vertex normals not used at the moment, normals are assumed to be pointing straight up)
		//mediump float ndoth = max( c_zero, dot( a_Normal, halfVector ) );
		mediump float ndoth = max( c_zero, halfVector.y );

		// Per vertex spec
		v_SpecularColour = u_LightSpecularColour * mu_MaterialSpecularColour * pow( ndoth, mu_MaterialSpecularPower );
	#endif
#endif

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

#ifdef DETAIL
	// Detail map
	calcDetailMapCoordVec( a_Position, u_EyePosModelSpace, mu_DetailFreq, v_DetailMapCoord );
	v_DetailMapCoord += vec2( u_detailTextureOffset );
#endif

#ifdef FOG
	#ifdef SUN_FOG
		// Lerp sun factor
		highp float sunFogFactor = clamp(-dot(u_LightDirModelSpace, vertexToEyeModelSpace), 0.0, 1.0);
		sunFogFactor = pow(sunFogFactor, u_FogSunPower);
		highp vec3 fogParams = mix(u_FogParams, u_FogSunParams, sunFogFactor);

		// Increase with distance up to max saturation
		v_FogFactor = clamp( (pos.w - fogParams.x) * fogParams.y, c_zero, fogParams.z );
		v_FogColour = mix(u_FogColour, u_FogSunColour, sunFogFactor);
	#else
		v_FogFactor = clamp( (pos.w - u_FogParams.x) * u_FogParams.y, c_zero, u_FogParams.z );
	#endif
#endif

	gl_Position = pos;
}
