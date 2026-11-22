
//WARNING: This must match the BakeShaderVariation enum in CarLiveryBaker.cpp
//%0define BAKE_STENCIL

//%1define BAKE_DECAL_NO_OCCLUSION

//%2define BAKE_DECAL_NO_OCCLUSION
//%2define USE_STEP_FUNCTION

//%3define BAKE_DECAL_NO_OCCLUSION
//%3define USE_FLAT_ALPHA

//%4define BAKE_DECAL_NO_OCCLUSION
//%4define USE_LIVERY_TEXTURE_RGB

//%5define BAKE_DECAL_NO_OCCLUSION
//%5define USE_STEP_FUNCTION
//%5define USE_LIVERY_TEXTURE_RGB

//%6define BAKE_DECAL_NO_OCCLUSION
//%6define USE_FLAT_ALPHA
//%6define USE_LIVERY_TEXTURE_RGB

//%7define BAKE_DECAL_DEPTH_TEST

//%8define BAKE_DECAL_DEPTH_TEST
//%8define USE_STEP_FUNCTION

//%9define BAKE_DECAL_DEPTH_TEST
//%9define USE_FLAT_ALPHA

//%10define BAKE_DECAL_DEPTH_TEST
//%10define USE_LIVERY_TEXTURE_RGB

//%11define BAKE_DECAL_DEPTH_TEST
//%11define USE_STEP_FUNCTION
//%11define USE_LIVERY_TEXTURE_RGB

//%12define BAKE_DECAL_DEPTH_TEST
//%12define USE_FLAT_ALPHA
//%12define USE_LIVERY_TEXTURE_RGB

//%13define BAKE_DECAL_BACKFACE_TEST

//%14define BAKE_DECAL_BACKFACE_TEST
//%14define USE_STEP_FUNCTION

//%15define BAKE_DECAL_BACKFACE_TEST
//%15define USE_FLAT_ALPHA

//%16define BAKE_DECAL_BACKFACE_TEST
//%16define USE_LIVERY_TEXTURE_RGB

//%17define BAKE_DECAL_BACKFACE_TEST
//%17define USE_STEP_FUNCTION
//%17define USE_LIVERY_TEXTURE_RGB

//%18define BAKE_DECAL_BACKFACE_TEST
//%18define USE_FLAT_ALPHA
//%18define USE_LIVERY_TEXTURE_RGB

//%19define BAKE_COPY
//%20define BAKE_EDGES
//%21define BAKE_COLOUR
//%22define BAKE_SPEC
//%23define BAKE_DEPTH

///////////////////////////////////////

//%feature BAKE_STENCIL
//%feature BAKE_DECAL_NO_OCCLUSION
//%feature BAKE_DECAL_DEPTH_TEST
//%feature BAKE_DECAL_BACKFACE_TEST
//%feature BAKE_COPY
//%feature BAKE_EDGES
//%feature BAKE_COLOUR
//%feature BAKE_SPEC
//%feature BAKE_DEPTH
//%feature USE_STEP_FUNCTION
//%feature USE_FLAT_ALPHA
//%feature USE_LIVERY_TEXTURE_RGB

//TODO: this could be cleaned up now with shader features - USE_STEP_FUNCTION could be always defined and masked by the device settings
//%precompile BAKE_STENCIL
//%precompile BAKE_DECAL_NO_OCCLUSION
//%precompile BAKE_DECAL_NO_OCCLUSION, USE_STEP_FUNCTION
//%precompile BAKE_DECAL_NO_OCCLUSION, USE_FLAT_ALPHA
//%precompile BAKE_DECAL_NO_OCCLUSION, USE_LIVERY_TEXTURE_RGB
//%precompile BAKE_DECAL_NO_OCCLUSION, USE_LIVERY_TEXTURE_RGB, USE_STEP_FUNCTION
//%precompile BAKE_DECAL_NO_OCCLUSION, USE_LIVERY_TEXTURE_RGB, USE_FLAT_ALPHA
//%precompile BAKE_DECAL_DEPTH_TEST
//%precompile BAKE_DECAL_DEPTH_TEST, USE_STEP_FUNCTION
//%precompile BAKE_DECAL_DEPTH_TEST, USE_FLAT_ALPHA
//%precompile BAKE_DECAL_DEPTH_TEST, USE_LIVERY_TEXTURE_RGB
//%precompile BAKE_DECAL_DEPTH_TEST, USE_LIVERY_TEXTURE_RGB, USE_STEP_FUNCTION
//%precompile BAKE_DECAL_DEPTH_TEST, USE_LIVERY_TEXTURE_RGB, USE_FLAT_ALPHA
//%precompile BAKE_DECAL_BACKFACE_TEST
//%precompile BAKE_DECAL_BACKFACE_TEST, USE_STEP_FUNCTION
//%precompile BAKE_DECAL_BACKFACE_TEST, USE_FLAT_ALPHA
//%precompile BAKE_DECAL_BACKFACE_TEST, USE_LIVERY_TEXTURE_RGB
//%precompile BAKE_DECAL_BACKFACE_TEST, USE_LIVERY_TEXTURE_RGB, USE_STEP_FUNCTION
//%precompile BAKE_DECAL_BACKFACE_TEST, USE_LIVERY_TEXTURE_RGB, USE_FLAT_ALPHA
//%precompile BAKE_COPY
//%precompile BAKE_EDGES
//%precompile BAKE_COLOUR
//%precompile BAKE_SPEC
//%precompile BAKE_DEPTH


#if defined(BAKE_COPY) || defined(BAKE_COLOUR) || defined(BAKE_SPEC)

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0
varying highp vec2 v_TexCoord0;

void main()
{
	v_TexCoord0 = a_TexCoord0;
	gl_Position = vec4( a_Position.xy, 0.0, 1.0 );
}

#endif

#if defined(BAKE_EDGES)

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0

varying highp vec2 v_TexCoord0;
varying highp vec2 v_TexCoord1;
varying highp vec2 v_TexCoord2;
varying highp vec2 v_TexCoord3;

uniform highp float u_PointSize; //inverse of texture size

void main()
{
	v_TexCoord0 = a_TexCoord0 + vec2( 0.0,  u_PointSize );
	v_TexCoord1 = a_TexCoord0 + vec2( 0.0, -u_PointSize );
	v_TexCoord2 = a_TexCoord0 + vec2(  u_PointSize, 0.0 );
	v_TexCoord3 = a_TexCoord0 + vec2( -u_PointSize, 0.0 );

	gl_Position = vec4( a_Position.xy, 0.0, 1.0 );
}

#endif

#if defined(BAKE_DECAL_NO_OCCLUSION) || defined(BAKE_DECAL_DEPTH_TEST) || defined(BAKE_DECAL_BACKFACE_TEST)

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0
attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL

uniform highp mat4 u_ModelToProj;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

varying highp vec2 v_TexCoordDecal;
varying highp vec4 v_Normal;
varying highp float v_Depth;

void main()
{
	// Project geometry into decal texture space
	highp vec4 clipCoord = u_ModelToProj * vec4(a_Position, 1.0);
	highp vec2 texCoord = (clipCoord.xy / clipCoord.w) * vec2(0.5) + vec2(0.5);
	v_TexCoordDecal = texCoord;

	// Not actually the correct way to transform normal but doesn't matter, we only want Z sign for backfaces
	v_Normal = u_ModelToProj * vec4(a_Normal, 0.0);

	// Z coord in decal clip space for shadow mapping
	v_Depth = ((clipCoord.z / clipCoord.w) * 0.5) + 0.5;

	// Transform texture coordinates into screen clip space
	gl_Position = vec4( a_TexCoord0 * uvMult * vec2(2.0) - vec2(1.0), 0.0, 1.0 );
}

#endif

#if defined(BAKE_STENCIL)

attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	// Transform texture coordinates into screen clip space
	gl_Position = vec4( a_TexCoord0 * uvMult * vec2(2.0) - vec2(1.0), 0.0, 1.0 );
}

#endif


#if defined(BAKE_DEPTH)

attribute highp vec3 a_Position;	//%attributeID MT_POS
uniform highp mat4 u_ModelToProj;

void main()
{
	// Project geometry into decal texture space
	gl_Position = u_ModelToProj * vec4(a_Position, 1.0);
}

#endif
