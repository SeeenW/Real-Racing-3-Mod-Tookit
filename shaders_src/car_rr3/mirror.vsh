//
//  mirror.vsh
//
//  Created by Patrick on 09/08/12.
//  Copyright Electronic Arts 2012. All rights reserved.
//

//%precompile

const highp float c_zero = 0.0;
const highp float c_one = 1.0;

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL

// Uniforms
// ----------------------------------------------------------------------

// Light info
uniform highp vec3 u_EyePosModelSpace;

// Transformation Matrices
uniform highp mat4 u_ModelToProj;
uniform highp mat4 u_ModelToWorld;

uniform mediump float u_MirrorPitch;
uniform mediump float u_MirrorYaw;
uniform highp vec4 u_SkyRotation; // Packed Y-Axis rotation matrix of the sky dome. mat2(u_SkyRotation.xy, u_SkyRotation.zw)

// ======================================================================
// Outputs
// ======================================================================

varying mediump vec3 v_CubeRay;

void main()
{
	highp float sinx = sin( radians( u_MirrorPitch ) );
	highp float cosx = cos( radians( u_MirrorPitch ) );
	highp float siny = sin( radians( u_MirrorYaw ) );
	highp float cosy = cos( radians( u_MirrorYaw ) );

	// This is simply the 3D rotation matrices for pitch and yaw multiplied together (specified in column major order).
	highp mat3 normalMatrix = mat3( cosy,  sinx * siny, -cosx * siny,
									 0.0,         cosx,         sinx,
									siny, -cosy * sinx,  cosx * cosy );

	// Vector eye to vertex in model space
	highp vec3 eyeToVertexModelSpace = normalize( a_Position - u_EyePosModelSpace );

	// Cube map reflection

	highp vec3 reflection = reflect( eyeToVertexModelSpace, normalMatrix * a_Normal );
	//v_CubeRay = mat3(u_ModelToWorld) * reflection; //ILeben: mat3(mat4) seems to have problems on Android
	v_CubeRay = (u_ModelToWorld * vec4(reflection, 0.0)).xyz;
	// rotate the world space reflection dir around Y-axis to match the sky dome orientation.
	highp mat2 skyRotation = mat2(u_SkyRotation.xy, u_SkyRotation.zw);
	v_CubeRay.xz = skyRotation * v_CubeRay.xz;
	v_CubeRay.xy = -v_CubeRay.xy;

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );
	gl_Position = pos;
}

