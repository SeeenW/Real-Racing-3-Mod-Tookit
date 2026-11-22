//
//  ground_norm_low.vsh
//
//  Created by Patrick on 20/09/12.
//  Copyright Electronic Arts 2012. All rights reserved.
//
//%0define QUALITY_LEVEL 0
//%1define QUALITY_LEVEL 1
//%2define NIGHT

//////////////////////////////////// NEW FEATURES SYSTEM

//%feature ROAD_NEW
//%feature NIGHT
//%feature HIGH_HL
//%feature LOW_HL

//%precompile
//%precompile NIGHT

//%include utility.xsh

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;		//%attributeID MT_POS
attribute highp vec3 a_Normal;			//%attributeID MT_NORMAL		NOTE: This isn't used at the moment, normals are assumed to be pointing straight up.
attribute mediump vec2 a_TexCoord0;		//%attributeID MT_UV_0	Diffuse UV channel
attribute mediump vec2 a_TexCoord1;		//%attributeID MT_UV_1	Shadow map UV channel

// Uniforms
// ----------------------------------------------------------------------

// Light info
uniform highp vec3 u_EyePosModelSpace;

// Fog
uniform mediump float u_FogStart;
uniform mediump float u_FogFactor;

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

// Material uniforms
uniform mediump float mu_DiffuseFreq;
uniform mediump float mu_DetailFreq;

#ifdef PER_VERTEX_SPEC
uniform mediump vec3 u_LightDirModelSpace;
uniform lowp vec3 u_LightSpecularColour;
// Material spreadsheet uniforms
uniform mediump float mu_MaterialSpecularPower;
uniform lowp vec3 mu_MaterialSpecularColour;
#endif

// ======================================================================
// Outputs
// ======================================================================

varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;
varying mediump vec2 v_DetailMapCoord;
//varying lowp float v_FogFactor;
//varying lowp vec3 v_SpecularColour;
varying lowp vec4 v_Spec_Fog;

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	uniform highp mat4 u_HeadLightMatrix;
	varying highp vec3 v_PosHeadLightSpace;
#endif

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	// Texture coords
	v_TexCoord0 = (a_TexCoord0 * mu_DiffuseFreq) * uvMult;
	v_TexCoord1 = a_TexCoord1 * uvMult;

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

	// Detail map
	calcDetailMapCoordVec( a_Position, u_EyePosModelSpace, mu_DetailFreq, v_DetailMapCoord);

#ifdef PER_VERTEX_SPEC
	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = u_EyePosModelSpace - a_Position;
	
	// Half vector
	mediump vec3 halfVector = normalize( (u_LightDirModelSpace * length( vertexToEyeModelSpace )) + vertexToEyeModelSpace );
	
	// N dot H
	mediump float ndoth = max( c_zero, dot( a_Normal, halfVector ) );

	// Per vertex spec
	//v_SpecularColour = u_LightSpecularColour * mu_MaterialSpecularColour * pow( ndoth, mu_MaterialSpecularPower );
	v_Spec_Fog.rgb = u_LightSpecularColour * mu_MaterialSpecularColour * pow( ndoth, mu_MaterialSpecularPower );
#endif

#if defined(NIGHT) && (defined(HIGH_HL) || defined(LOW_HL))
	v_PosHeadLightSpace = (u_HeadLightMatrix * vec4(a_Position, 1.0)).xyz;
#endif

	// Fog
	//v_FogFactor = clamp( (pos.w - u_FogStart) * u_FogFactor, c_zero, c_one );
	v_Spec_Fog.a = clamp( (pos.w - u_FogStart) * u_FogFactor, c_zero, c_one );

	gl_Position = pos;
}

