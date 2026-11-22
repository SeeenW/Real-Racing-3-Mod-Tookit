//
//  reflect_hemisphere.vsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

//%feature SUN_FOG
//%feature NIGHT
//%feature NOBIAS

//%precompile SUN_FOG
//%precompile

const lowp float c_zero = 0.0;
const lowp float c_half = 0.5;
const lowp float c_one = 1.0;
const highp float c_inv_sqrt_2 = 0.707106781186547524401;
const highp vec4 c_eyeView = vec4(vec3(c_zero), c_one);
const highp vec2 c_halfv2 = vec2(c_half);
const highp float c_inv_sqrt_2_half = c_inv_sqrt_2 * c_half;

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL
attribute mediump vec2 a_TexCoord0;	//%attributeID MT_UV_0
attribute mediump vec2 a_TexCoord1;	//%attributeID MT_UV_1

// Uniforms
// ----------------------------------------------------------------------

// Fog
#ifdef SUN_FOG
	uniform highp vec3 u_LightDirModelSpace;

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

// Transformation Matrices
uniform highp mat4 u_ModelToProj;
uniform highp mat4 u_ModelToWorld;
uniform highp mat4 u_ModelToView;
uniform highp mat3 u_NormalToViewRotMatrix;

uniform highp vec3 u_EyePosModelSpace;
uniform highp vec4 u_SkyRotation; // Packed Y-Axis rotation matrix of the sky dome. mat2(u_SkyRotation.xy, u_SkyRotation.zw)

// Material uniforms
uniform mediump float mu_FresnelFactor;

// ======================================================================
// Outputs
// ======================================================================

varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;
varying mediump vec2 v_HemiUV;
varying mediump float v_FresnelCoeff;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	// TODO:
	// This shader is still using the old method of looking up the hemi map etc... I'm sure it could be optimised a bit.

	// Texture coords
	v_TexCoord0 = a_TexCoord0 * uvMult;
	v_TexCoord1 = a_TexCoord1 * uvMult;

	highp vec3 eyeToVertex = a_Position - u_EyePosModelSpace;

	//highp vec3 reflection = normalize(mat3(u_ModelToWorld) * reflect(eyeToVertex, a_Normal)); //ILeben: mat3(mat4) seems to have problems on Android
	highp vec3 reflection = normalize((u_ModelToWorld * vec4(reflect(eyeToVertex, a_Normal), 0.0)).xyz);

	// rotate the world space reflection dir around Y-axis to match the sky dome orientation.
	highp mat2 skyRotation = mat2(u_SkyRotation.xy, u_SkyRotation.zw);
	reflection.xz = skyRotation * reflection.xz;

	highp float invLength = c_inv_sqrt_2_half * inversesqrt(c_one + reflection.y);
	v_HemiUV = vec2(-reflection.x, reflection.z) * invLength + c_halfv2;

	v_FresnelCoeff = (c_one - max(c_zero, dot(a_Normal, -normalize(eyeToVertex))-0.2));
	v_FresnelCoeff = smoothstep(c_zero, c_one, v_FresnelCoeff) * mu_FresnelFactor;

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

	// Fog
	#ifdef SUN_FOG
		highp float sunFogFactor = clamp(dot(u_LightDirModelSpace, normalize(eyeToVertex)), 0.0, 1.0);
		sunFogFactor = pow(sunFogFactor, u_FogSunPower);
		highp vec3 fogParams = mix(u_FogParams, u_FogSunParams, sunFogFactor);

		// Increase with distance up to max saturation
		v_FogFactor = clamp( (pos.w - fogParams.x) * fogParams.y, 0.0, fogParams.z );
		v_FogColour = mix(u_FogColour, u_FogSunColour, sunFogFactor);
	#else
		v_FogFactor = clamp( (pos.w - u_FogParams.x) * u_FogParams.y, 0.0, u_FogParams.z );
	#endif

	gl_Position = pos;
}

