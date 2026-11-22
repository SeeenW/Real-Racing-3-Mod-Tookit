//%0define PASS_THROUGH
//%1define BLUR_HORIZONTAL
//%2define BLUR_VERTICAL
//%3define CUBEMAP_TO_SPHERICAL
//%4define SPHERICAL_TO_CUBEMAP

////////////////////////////////////

//%feature PASS_THROUGH
//%feature BLUR_HORIZONTAL
//%feature BLUR_VERTICAL
//%feature CUBEMAP_TO_SPHERICAL
//%feature SPHERICAL_TO_CUBEMAP

//%precompile PASS_THROUGH
//%precompile BLUR_HORIZONTAL
//%precompile BLUR_VERTICAL
//%precompile CUBEMAP_TO_SPHERICAL
//%precompile SPHERICAL_TO_CUBEMAP

attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

#ifdef CUBEMAP_TO_SPHERICAL

uniform highp mat4 u_ViewToProj;
varying highp vec2 v_TexCoord0;

void main()
{
	//translate into [-1, 1] range
	v_TexCoord0 = (a_TexCoord0 * 2.0) - vec2(1.0);
	gl_Position = u_ViewToProj * vec4( a_Position, 1.0 );
}

#else

uniform highp mat4 u_ModelToView;	//plane to cube transform
uniform highp mat4 u_ViewToProj;	//just projection (actual modelview would've been identity anyway)

varying highp vec3 v_CubeCoord;

#if defined(BLUR_HORIZONTAL) || defined(BLUR_VERTICAL)

varying highp vec3 v_CubeDirX;
varying highp vec3 v_CubeDirY;

#endif

void main()
{
	//translate into [-1, 1] range for cubemap lookup
	highp vec2 planeCoord = (a_TexCoord0 * 2.0) - vec2(1.0);

	//this will point it towards the current cube face
	v_CubeCoord = (u_ModelToView * vec4(planeCoord, 0.0, 1.0)).rgb;

#if defined(BLUR_HORIZONTAL) || defined(BLUR_VERTICAL)

	//first and second column tell us which way the blur offset goes
	v_CubeDirX = u_ModelToView[0].rgb;
	v_CubeDirY = u_ModelToView[1].rgb;

#endif

	gl_Position = u_ViewToProj * vec4( a_Position, 1.0 );
}
#endif
