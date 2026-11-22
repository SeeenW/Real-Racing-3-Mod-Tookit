//  ground_mirror.vsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.


//This shader doesn't seem to be used, so I'm not going to bother refactoring it to use features
//%feature FIXME_I_THOUGHT_THIS_WAS_UNUSED

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0		Diffuse UV channel
attribute highp vec2 a_TexCoord1;	//%attributeID MT_UV_1		Shadow map UV channel

// Uniforms
// ----------------------------------------------------------------------

// Light info
uniform highp vec3 u_EyePosModelSpace;
uniform highp vec3 u_LightDirModelSpace;

#ifdef FOG
	#ifdef SUN_FOG
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

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

// Material uniforms
uniform mediump float mu_DiffuseFreq;
uniform mediump float mu_DetailFreq;

// ======================================================================
// Outputs
// ======================================================================

varying highp vec2 v_TexCoord0;
varying highp vec2 v_TexCoord1;
varying highp vec3 v_HalfVector;

#ifdef FOG
varying lowp float v_FogFactor;
varying lowp vec3 v_FogColour;
#endif //FOG

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	// Texture coords
	v_TexCoord0 = a_TexCoord0 * uvMult;
	v_TexCoord1 = a_TexCoord1 * uvMult;

	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = u_EyePosModelSpace - a_Position;

	// Half vector
	v_HalfVector = (u_LightDirModelSpace * length( vertexToEyeModelSpace )) + vertexToEyeModelSpace;

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

#ifdef FOG
	#ifdef SUN_FOG
		float sunFogFactor = clamp(dot(u_LightDirModelSpace, normalize(a_Position - u_EyePosModelSpace)), 0.0, 1.0);
		sunFogFactor = pow(sunFogFactor, u_FogSunPower);
		vec3 fogParams = mix(u_FogParams, u_FogSunParams, sunFogFactor);

		// Increase with distance up to max saturation
		v_FogFactor = clamp( (pos.w - fogParams.x) * fogParams.y, 0.0, fogParams.z );
		v_FogColour = mix(u_FogColour, u_FogSunColour, sunFogFactor);
	#else
		v_FogFactor = clamp( (pos.w - u_FogParams.x) * u_FogParams.y, 0.0, u_FogParams.z );
	#endif
#endif


	gl_Position = pos;
}



