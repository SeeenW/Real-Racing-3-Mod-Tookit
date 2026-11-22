//
//  basic_lighting.vsh
//
//  Copyright Electronic Arts 2012. All rights reserved.
//

//%0define QUALITY_LEVEL 0
//%1define QUALITY_LEVEL 1
//%2define NIGHT

//////////////////////////////

//%feature FOG
//%feature SUN_FOG
//%feature TREES
//%feature NIGHT
//%feature HIGH_HL
//%feature LOW_HL
//%feature WIREFENCE
//%feature ALPHA_MODULATE

//%precompile -FOG
//%precompile SUN_FOG
//%precompile SUN_FOG, NIGHT

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

#ifndef ENABLE_SHADER_FEATURES

// Enable high-quality fog
#ifndef SUN_FOG
#define SUN_FOG
#endif

#endif//ENABLE_SHADER_FEATURES

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL
attribute mediump vec2 a_TexCoord0;	//%attributeID MT_UV_0		Diffuse UV channel

// Uniforms
// ----------------------------------------------------------------------

// Light information
#ifdef TREES
	uniform lowp vec3 u_TreeDiffuseColour;
#else
	uniform lowp vec3 u_LightDiffuseColour;
#endif

uniform highp vec3 u_LightDirModelSpace;
uniform highp vec3 u_EyePosModelSpace;

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
#endif

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

// ======================================================================
// Outputs
// ======================================================================

varying mediump vec2 v_TexCoord0;
varying highp vec3 v_VertexNormalModelSpace;
varying lowp vec3 v_DiffuseColour;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	v_PosHeadLightSpace = (u_HeadLightMatrix * vec4(a_Position, 1.0)).xyz;
#endif

	v_TexCoord0 = a_TexCoord0 * uvMult;

	// Normal in model space
	v_VertexNormalModelSpace = a_Normal;

	// N dot L
	highp float ndotl = max( c_zero, dot( a_Normal, u_LightDirModelSpace ));

	// Diffuse lighting
#ifdef TREES
	v_DiffuseColour = (ndotl * u_TreeDiffuseColour);
#else
	v_DiffuseColour = (ndotl * u_LightDiffuseColour);
#endif
	
	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

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

	// Fog
	//v_FogFactor = clamp( (pos.w - u_FogStart) * u_FogFactor, c_zero, u_FogSaturation );

	gl_Position = pos;
}

