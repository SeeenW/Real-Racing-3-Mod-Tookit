//
//  windscreen_cracks.vsh
//
//  Created by vchau on 15/05/12.
//  Copyright Firemint 2012. All rights reserved.
//

#ifndef ENABLE_SHADER_FEATURES
	#ifndef DONT_USE_CAR_REFLECTION
		#ifndef CUBE_MAP
		#define CUBE_MAP
		#endif
	#endif
#endif

//%feature CUBE_MAP
//%precompile CUBE_MAP

const float c_zero = 0.0;
const float c_one = 1.0;
const lowp vec3 c_rgbToLuma = vec3(0.299, 0.587, 0.114);
const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

// Inputs
// -----------------------------------

// Vertex attributes
attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec3 a_Normal;	//%attributeID MT_NORMAL
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

// Transformation Matrices
uniform highp mat4 u_ModelToProj;
uniform highp mat4 u_ModelToWorld;

// Light info
uniform lowp vec3 u_LightAmbientColour;
uniform highp vec3 u_EyePosModelSpace;
uniform highp vec3 u_LightDirModelSpace;
uniform highp vec3 u_LightDiffuseColourTimesScaleFactor;

// Outputs
// -----------------------------------

varying mediump vec2 v_TexCoord0;
varying lowp vec3 v_DiffuseColour;

#ifdef CUBE_MAP
varying mediump vec3 v_CubeRay;
#endif

void main()
{
	v_TexCoord0 = a_TexCoord0 * uvMult;

	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );

	// Vector from the eye to vertex in model space
	highp vec3 eyeToVertexModelSpace = normalize(a_Position - u_EyePosModelSpace);

	// N dot L
	lowp float ndotl = 0.2 * max(0.0, dot( eyeToVertexModelSpace, u_LightDirModelSpace ));

	// Diffuse
	v_DiffuseColour = vec3(ndotl, ndotl, ndotl);

	// Cube map refraction
#ifdef CUBE_MAP
	//v_CubeRay = mat3(u_ModelToWorld) * eyeToVertexModelSpace; //ILeben: mat3(mat4) seems to have problems on Android
	v_CubeRay = (u_ModelToWorld * vec4(eyeToVertexModelSpace, 0.0)).xyz;
	v_CubeRay.xy = -v_CubeRay.xy;
#endif

	gl_Position = pos;
}

