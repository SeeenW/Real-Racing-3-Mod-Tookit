//
//  car_interior.vsh
//
//  Created by bend on 10/07/12.
//  Copyright Electronic Arts 2012. All rights reserved.
//

//%0define USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
//%1define USE_SHADOW_MAP
//%2define USE_SH_LIGHTING

//%3define USE_SH_LIGHTING
//%3define DIFFUSE_LIGHTING

////////////////////////////////////////////// NEW FEATURES SYSTEM

//%feature USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
//%feature USE_SHADOW_MAP
//%feature USE_SH_LIGHTING
//%feature DIFFUSE_LIGHTING

//%precompile USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
//%precompile USE_SHADOW_MAP
//%precompile USE_SH_LIGHTING

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL
attribute mediump vec2 a_TexCoord0;	//%attributeID MT_UV_0
attribute mediump vec2 a_TexCoord1;	//%attributeID MT_UV_1

// Transformation Matrices
uniform highp mat4 u_ModelToProj;
uniform highp mat4 u_ModelToWorld;

// Light info
uniform highp vec3 u_EyePosModelSpace;
uniform highp mat3 u_NormalToViewRotMatrix;
uniform mediump vec3 u_LightDiffuseColour;

varying mediump vec2 v_TexCoord0;
varying mediump vec2 v_TexCoord1;
varying mediump vec2 v_EdotN;
varying lowp vec3 v_CubeRay;
varying lowp float v_CubeReflectionModulate;

varying lowp vec3 v_DiffuseColour;
varying highp vec3 v_VertexNormalModelSpace;
varying highp vec3 v_HalfVectorModelSpace;

#ifdef USE_SHADOW_MAP
	uniform highp mat4 u_ModelToShadow;
	varying lowp vec2 v_ShadowUV;
#endif

#ifdef USE_SH_LIGHTING
	uniform mediump vec4 u_SHLightCoeffs[7];
	uniform highp vec3 u_SHSpecDir;
	#define u_LIGHT_DIR_MODEL_SPACE u_SHSpecDir
#else
	uniform highp vec3 u_LightDirModelSpace;
	#define u_LIGHT_DIR_MODEL_SPACE u_LightDirModelSpace
#endif

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	// Texture coords
	v_TexCoord0 = a_TexCoord0 * uvMult;
	v_TexCoord1 = a_TexCoord1 * uvMult;

	// Normal in model space
	v_VertexNormalModelSpace = a_Normal;

	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = normalize( u_EyePosModelSpace - a_Position );

	// Half vector
	// (Don't need to normalize here - do it per pixel anyway)
	// EDIT: Actually, had to normalise it here because it fixed some issues with the specular reflection
	// appearing on the roof which was really strange.
	v_HalfVectorModelSpace = normalize( u_LIGHT_DIR_MODEL_SPACE + vertexToEyeModelSpace );

	// E dot N (for looking up the fresnel term from the fresnel texture)
	v_EdotN = vec2( c_one - max( c_zero, dot( vertexToEyeModelSpace, a_Normal ) ), c_zero );

	// N dot L
	highp float ndotl = max( c_zero, dot( a_Normal, u_LIGHT_DIR_MODEL_SPACE ));

	// Diffuse
#ifdef USE_SH_LIGHTING
	mediump vec3 n = normalize((u_ModelToWorld * vec4(a_Normal, 0.0)).xyz);
	mediump vec4 vA = vec4(n, 1.0);
	mediump vec3 x1 = vec3(dot(u_SHLightCoeffs[0], vA), dot(u_SHLightCoeffs[1], vA), dot(u_SHLightCoeffs[2], vA));
	mediump vec4 vB = n.xxyz * n.yzzz;
	mediump vec3 x2 = vec3(dot(u_SHLightCoeffs[3], vB), dot(u_SHLightCoeffs[4], vB), dot(u_SHLightCoeffs[5], vB));
	mediump vec3 vC = vec3(n.x*n.x - n.y*n.y);
	mediump vec3 x3 = u_SHLightCoeffs[6].rgb * vC;
	v_DiffuseColour = (x1 + x2 + x3);
#else
	v_DiffuseColour = ndotl * u_LightDiffuseColour;
#endif

	// Cube map reflection
	highp vec3 reflection = reflect( -vertexToEyeModelSpace, a_Normal );
	v_CubeRay = (u_ModelToWorld * vec4(reflection, 0.0)).xyz; //ILeben: mat3(mat4) seems to have problems on Android
	v_CubeRay.xy = -v_CubeRay.xy;

	// This calculates the y component of the vertex normal in view space, and clamps it to the range [0, 1].
	// We use this to reduce the cube map reflection on faces that face downwards.
	v_CubeReflectionModulate = min( normalize( u_NormalToViewRotMatrix * a_Normal ).y + 1.0, 1.0 );

#ifdef USE_SHADOW_MAP
	v_ShadowUV = (u_ModelToShadow * vec4( a_Position, c_one )).xz;
#endif

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );
	
	gl_Position = pos;
}

