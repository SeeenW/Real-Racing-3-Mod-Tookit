//
//  diffuse_no_lighting.vsh
//
//  Created by ianu on 27/10/10 from basic_no_lighting.vsh
//  Copyright Firemint 2009. All rights reserved.
//
//%include utility.xsh

uniform lowp vec4 u_CurrentColour;

varying lowp vec4 v_FogColor;

varying lowp vec4 v_VertexColor;

varying mediump vec2 v_TexCoord0;
uniform lowp sampler2D s_Texture0;

#ifdef PARTICLE_SOFT_FADE
	varying highp vec2 v_TexCoord2;

	uniform lowp sampler2D s_Texture2;		// Depth texture

	uniform mediump vec2 u_ViewportSizeInv;

	uniform highp float u_Proj_33;
	uniform highp float u_Proj_34_Negative;
	lowp float perspectiveToWorldDepth( highp float perspectiveDepth )
	{
		return u_Proj_34_Negative / (perspectiveDepth + u_Proj_33);
	}

	//uniform highp float u_NearClip;
	//uniform highp float u_FarClip;
	//uniform highp float u_FarMinusNear;
	//highp float lineariseDepth( highp float depth )
	//{
	//	return (2.0 * u_NearClip) / (u_FarClip + u_NearClip - (depth * u_FarMinusNear));	
	//}
#endif

void main()
{
	lowp vec4 c = texture2DWithBias( s_Texture0, v_TexCoord0 ) * u_CurrentColour;
	c = c * v_VertexColor;
	c.rgb = c.rgb * v_FogColor.a + v_FogColor.rgb;

#ifdef PARTICLE_SOFT_FADE
	mediump vec2 screenCoord = gl_FragCoord.xy * u_ViewportSizeInv;
	highp float depth = texture2D( s_Texture2, screenCoord ).r;

	highp float worldDepth = perspectiveToWorldDepth( depth );
	highp float particleDepth = perspectiveToWorldDepth( gl_FragCoord.z );
	highp float diff = v_TexCoord2.x * (particleDepth - worldDepth);
	
	c.a *= min( diff, 1.0 );

	// Debugging
	//c = vec4( diff, diff, diff, 1.0 );
#endif

	gl_FragColor = c;
}

