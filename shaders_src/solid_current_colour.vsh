//%precompile

const lowp float c_one = 1.0;

attribute highp vec3 a_Position;	//%attributeID MT_POS

uniform highp mat4 u_ModelToProj;

void main()
{
	gl_Position = u_ModelToProj * vec4( a_Position, c_one );
}
