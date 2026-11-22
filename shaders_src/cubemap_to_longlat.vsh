
//%debugshader

attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

uniform highp mat4 u_ViewToProj;
varying highp vec2 v_TexCoord0;

const highp float PI = 3.1415927;

uniform highp float u_LongitudeCentre;

void main()
{
	v_TexCoord0 = vec2( 2.0 * PI * (a_TexCoord0.x) - (u_LongitudeCentre + PI*0.5),
						0.5 * PI * (a_TexCoord0.y * 2.0 - 1.0));

	gl_Position = u_ViewToProj * vec4( a_Position, 1.0 );
}
