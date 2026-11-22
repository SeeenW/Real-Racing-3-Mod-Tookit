//
//  car_interior_low.vsh
//
//  Created by bend on 10/07/12.
//  Copyright Electronic Arts 2012. All rights reserved.
//

//%0define DUMMY_VARIATION_1
//%1define DUMMY_VARIATION_2
//%2define USE_SH_LIGHTING

//%3define USE_SH_LIGHTING
//%3define DIFFUSE_LIGHTING

//////////////////////////////////////// NEW FEATURE SYSTEM

//%feature USE_SH_LIGHTING
//%feature DIFFUSE_LIGHTING

//%precompile USE_SH_LIGHTING
//%precompile

#ifdef USE_SH_LIGHTING
	uniform mediump vec4 u_SHLightCoeffs[7];
	uniform highp vec3 u_SHSpecDir;
	#define u_LIGHT_DIR_MODEL_SPACE u_SHSpecDir
#else
	uniform highp vec3 u_LightDirModelSpace;
	#define u_LIGHT_DIR_MODEL_SPACE u_LightDirModelSpace
#endif

//No dash-specific shader; no cubemap on dash

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL
attribute mediump vec2 a_TexCoord0;	//%attributeID MT_UV_0

// Transformation Matrices
uniform highp mat4 u_ModelToProj;
uniform highp mat4 u_ModelToWorld;

// Light info
uniform highp vec3 u_EyePosModelSpace;
uniform mediump vec3 u_LightDiffuseColourTimesScaleFactor;

varying mediump vec2 v_TexCoord0;
varying lowp vec3 v_DiffuseColour;

//varying highp vec2 v_NdotH;
varying highp vec3 v_VertexNormalModelSpace;
varying highp vec3 v_HalfVectorModelSpace;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	// Texture coords
	v_TexCoord0 = a_TexCoord0 * uvMult;

	// Normal in model space
	v_VertexNormalModelSpace = a_Normal;

	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = normalize( u_EyePosModelSpace - a_Position );

	// Half vector
	// (Don't need to normalize here - do it per pixel anyway)
	v_HalfVectorModelSpace = u_LIGHT_DIR_MODEL_SPACE + vertexToEyeModelSpace;

	// N dot H (for looking up the spec value from the spec texture)
	//v_NdotH = vec2( max( 0.001, dot( a_Normal, v_HalfVectorModelSpace ) ), c_zero );

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
	// N dot L
	highp float ndotl = max( c_zero, dot( a_Normal, u_LIGHT_DIR_MODEL_SPACE ));

	// Diffuse
	v_DiffuseColour = (ndotl * u_LightDiffuseColourTimesScaleFactor);
#endif

	// Position
	highp vec4 pos = u_ModelToProj * vec4( a_Position, c_one );
	
	gl_Position = pos;
}

